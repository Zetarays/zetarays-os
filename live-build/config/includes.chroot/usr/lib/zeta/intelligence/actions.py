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


from i18n import tr, ntr

from .providers.base import ToolSpec


def _popen(*a, **kw):
    """Popen che aspetta la fine del programma in sottofondo (niente zombie
    nel processo di ZETA, che resta aperto)."""
    import threading
    p = subprocess.Popen(*a, **kw)
    threading.Thread(target=p.wait, daemon=True).start()
    return p


LOG_FILE = Path(os.path.expanduser("~/.local/share/zeta/actions.log"))

# wpctl scrive il volume con il separatore decimale della lingua (0,40 in
# italiano): per leggerlo si chiede sempre la forma C (0.40)
_ENV_C = dict(os.environ, LC_ALL="C")


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
            return ActionResult(False, tr("Unknown action: {name}").format(name=name))
        self._log(name, args, action.level)
        # livelli 3/4: prima l'anteprima, poi l'esecuzione autorizzata
        if action.level >= 3 and not authorized:
            preview, impact = self._preview(action, args)
            return ActionResult(True, "", needs_confirmation=True,
                                preview=preview, impact=impact, level=action.level)
        try:
            return action.handler(args)
        except Exception as e:  # noqa: BLE001 — mai far cadere ZETA
            return ActionResult(False, tr("Error during “{action}”: {error}").format(action=name, error=e))

    def _preview(self, action: Action, args: dict) -> tuple[str, str]:
        arg_txt = ", ".join("%s=%s" % (k, v) for k, v in args.items())
        preview = "%s(%s)" % (action.name, arg_txt)
        impact = tr("Level {level} — {description}").format(level=action.level,
                                                          description=action.description)
        return preview, impact

    def _log(self, name: str, args: dict, level: int) -> None:
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_000_000:
                LOG_FILE.replace(LOG_FILE.with_name(LOG_FILE.name + ".1"))   # resta corto
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
            "system_info", 1, tr("Shows information about ZETA RAYS OS (version, kernel, CPU, memory)."),
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _system_info())))
        self.register(Action(
            "process_list", 1, tr("Lists the processes using the most CPU."),
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _run(["sh", "-c",
                "ps -eo pcpu,pmem,comm --sort=-pcpu | head -n 12"]))))
        self.register(Action(
            "disk_usage", 1, tr("Shows used and free disk space."),
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _run(["df", "-h", "--output=source,size,used,avail,pcent,target"]))))
        self.register(Action(
            "network_status", 1, tr("Shows the status of network connections."),
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _run(["sh", "-c",
                "nmcli -t -f DEVICE,TYPE,STATE device 2>/dev/null || ip -brief addr"]))))
        self.register(Action(
            "find_files", 1, tr("Searches the home folder for files by name or extension, optionally only recently modified ones."),
            {"type": "object",
             "properties": {"pattern": {"type": "string", "description": "e.g. *.pdf or *invoice*; several extensions separated by commas: *.jpg,*.png"},
                            "oggi": {"type": "boolean", "description": "only files modified today"},
                            "giorni": {"type": "integer", "description": "only files modified in the last N days"}},
             "required": ["pattern"]},
            _find_files))
        self.register(Action(
            "read_file", 1, tr("Reads a text file in the home folder."),
            {"type": "object",
             "properties": {"path": {"type": "string"}},
             "required": ["path"]},
            _read_file))
        self.register(Action(
            "security_status", 1, tr("Summary of the security status (firewall, updates…)."),
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _security_status())))

        self.register(Action(
            "cpu_usage", 1, tr("Shows the current CPU usage as a percentage."),
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _cpu_usage())))
        self.register(Action(
            "memory_usage", 1, tr("Shows how much memory (RAM) is in use and how much is free."),
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _memory_usage())))
        self.register(Action(
            "uptime", 1, tr("How long the system has been on."),
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _run(["sh", "-c", "uptime -p 2>/dev/null || uptime"]))))
        self.register(Action(
            "ip_address", 1, tr("Shows the system's local IP addresses."),
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _ip_address())))
        self.register(Action(
            "list_applications", 1, tr("Lists the installed graphical apps that can be opened."),
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _list_applications())))

        # LIVELLO 2 — azioni utente
        self.register(Action(
            "open_application", 2, tr("Opens an installed app (common name or executable)."),
            {"type": "object",
             "properties": {"app": {"type": "string"}},
             "required": ["app"]},
            _open_application))
        self.register(Action(
            "open_folder", 2, tr("Opens a folder in the file manager (e.g. documents, downloads, pictures, or a path)."),
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "documenti, download, immagini, musica, video, scrivania, home (or their English names), or a path"}},
             "required": ["name"]},
            _open_folder))
        self.register(Action(
            "open_settings", 2, tr("Opens ZETA RAYS Settings, optionally on a specific page."),
            {"type": "object",
             "properties": {"page": {"type": "string", "description": "page key: aspetto (appearance), rete (network), bluetooth, audio, ai, sicurezza (security), pacchetti (packages), informazioni (about)"}}},
            _open_settings))
        self.register(Action(
            "open_system_monitor", 2, tr("Opens the ZETA RAYS System Monitor (CPU, network, processes, firewall…)."),
            {"type": "object", "properties": {"section": {"type": "string"}}},
            lambda a: _launch("zeta-monitor", [a["section"]] if a.get("section") else [],
                              tr("System Monitor"))))
        self.register(Action(
            "open_security", 2, tr("Opens ZETA RAYS Security (firewall, security tools, system status)."),
            {"type": "object", "properties": {}},
            lambda a: _launch("zeta-sicurezza", [], "ZETA RAYS Security")))
        # Quando nessuna delle azioni qui sopra basta, ZETA non si arrende:
        # scrive il comando che servirebbe, lo mette negli appunti e apre il
        # terminale. A premere Invio sei tu. Cosi ZETA puo aiutare su
        # qualunque cosa senza che un modello da un miliardo di parametri
        # possa eseguire da solo qualcosa di irreversibile.
        # --- energia: livello 3, perche interrompono il lavoro dell utente ---
        self.register(Action(
            "lock_screen", 2, tr("Locks the screen."),
            {"type": "object", "properties": {}},
            lambda a: _energia("lock", tr("Locking the screen."))))
        self.register(Action(
            "log_out", 3, tr("Ends the session and returns to the login screen."),
            {"type": "object", "properties": {}},
            lambda a: _energia("logout", tr("Logging out."))))
        self.register(Action(
            "suspend", 3, tr("Suspends the computer."),
            {"type": "object", "properties": {}},
            lambda a: _energia("suspend", tr("Suspending the computer."))))
        self.register(Action(
            "reboot", 4, tr("Restarts the computer."),
            {"type": "object", "properties": {}},
            lambda a: _semplice(["systemctl", "reboot"], tr("Restarting."))))
        self.register(Action(
            "power_off", 4, tr("Shuts down the computer."),
            {"type": "object", "properties": {}},
            lambda a: _semplice(["systemctl", "poweroff"], tr("Shutting down."))))

        # --- suono e schermo ---
        self.register(Action(
            "set_volume", 2, tr("Sets the volume (0-100), raises or lowers it by a step, or mutes it."),
            {"type": "object",
             "properties": {"level": {"type": "integer", "description": "from 0 to 100"},
                            "step": {"type": "string", "enum": ["su", "giu"],
                                     "description": "su = up, giu = down, relative to the current volume"},
                            "amount": {"type": "integer", "description": "by how many points (default 10)"},
                            "mute": {"type": "boolean"}}},
            _set_volume))
        self.register(Action(
            "set_brightness", 2, tr("Sets the screen brightness (0-100)."),
            {"type": "object",
             "properties": {"level": {"type": "integer", "description": "from 0 to 100"}},
             "required": ["level"]},
            _set_brightness))

        # --- file e cartelle ---
        self.register(Action(
            "create_folder", 2, tr("Creates a folder in the home folder."),
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "name or path of the new folder"}},
             "required": ["name"]},
            _create_folder))
        self.register(Action(
            "screen_off", 2, tr("Turns off the screen (doesn't lock or shut down the computer)."),
            {"type": "object", "properties": {}},
            _screen_off))
        self.register(Action(
            "close_application", 2, tr("Closes a running program by name (e.g. Firefox)."),
            {"type": "object",
             "properties": {"app": {"type": "string", "description": "program name"}},
             "required": ["app"]},
            _close_application))
        self.register(Action(
            "screenshot", 2, tr("Saves a screenshot in the Pictures folder."),
            {"type": "object", "properties": {}},
            _screenshot))
        self.register(Action(
            "search_content", 1,
            tr("Searches for a word inside files, including the text of PDFs and text in images."),
            {"type": "object",
             "properties": {"text": {"type": "string", "description": "word or phrase to search for"}},
             "required": ["text"]},
            _search_content))
        self.register(Action(
            "rename_file", 3, tr("Renames a file or folder."),
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "current name or path"},
                            "new_name": {"type": "string", "description": "new name, without paths"}},
             "required": ["name", "new_name"]},
            _rename_file))
        self.register(Action(
            "move_file", 3, tr("Moves a file or folder into another folder."),
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "name or path of the file"},
                            "folder": {"type": "string", "description": "destination folder (documents, pictures…)"}},
             "required": ["name", "folder"]},
            _move_file))
        self.register(Action(
            "trash_file", 3, tr("Moves a file or folder to the Trash (can be restored)."),
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "name or path"}},
             "required": ["name"]},
            _trash_file))
        self.register(Action(
            "empty_trash", 3, tr("Empties the Trash. This can't be undone."),
            {"type": "object", "properties": {}},
            lambda a: _semplice(["sh", "-c", "gio trash --empty"], tr("Trash emptied."))))

        # --- programmi ---
        self.register(Action(
            "install_package", 4, tr("Installs a program from the system repositories."),
            {"type": "object",
             "properties": {"name": {"type": "string"}},
             "required": ["name"]},
            lambda a: _pacchetto("install", a)))
        self.register(Action(
            "remove_package", 4, tr("Removes an installed program."),
            {"type": "object",
             "properties": {"name": {"type": "string"}},
             "required": ["name"]},
            lambda a: _pacchetto("remove", a)))

        # --- rete ---
        self.register(Action(
            "wifi_toggle", 3, tr("Turns Wi-Fi on or off."),
            {"type": "object",
             "properties": {"on": {"type": "boolean"}},
             "required": ["on"]},
            lambda a: _semplice(["nmcli", "radio", "wifi", "on" if a.get("on") else "off"],
                                tr("Wi-Fi on.") if a.get("on") else tr("Wi-Fi off."))))

        # Nessuna azione «esegui un comando qualunque»: c'era (livello 4, con
        # conferma e perfino come amministratore) e va contro una regola di
        # ZETA RAYS: l'AI non ha mai accesso libero al sistema, men che meno
        # da root. Quando nessuna azione basta, ZETA prepara il comando nel
        # terminale e lo lascia decidere a chi sta davanti allo schermo.
        self.register(Action(
            "propose_command", 2,
            tr("Prepares a command in the terminal for the user, without running it. "
               "Use it when no other action covers the request."),
            {"type": "object",
             "properties": {
                 "command": {"type": "string",
                             "description": "the command, as it would be typed in the terminal"},
                 "why": {"type": "string",
                         "description": "what it is for, in one line"}},
             "required": ["command"]},
            _propose_command))
        self.register(Action(
            "open_file", 2, tr("Opens a file with the default app (document, image, video, archive…)."),
            {"type": "object",
             "properties": {"name": {"type": "string",
                                     "description": "name or path of the file, inside the home folder"}},
             "required": ["name"]},
            _open_file))
        self.register(Action(
            "open_url", 2, tr("Opens a web address in the browser."),
            {"type": "object",
             "properties": {"url": {"type": "string", "description": "http or https address"}},
             "required": ["url"]},
            _open_url))
        self.register(Action(
            "set_wallpaper", 3, tr("Changes the desktop wallpaper, or restores the ZETA RAYS one."),
            {"type": "object",
             "properties": {"name": {"type": "string",
                                     "description": "path of the image, or «predefinito» to go back to the ZETA RAYS one"}}},
            _set_wallpaper))
        self.register(Action(
            "open_terminal", 2, tr("Opens the terminal."),
            {"type": "object", "properties": {}},
            lambda a: _launch("foot", [], tr("Terminal"), tr("Opening the terminal."))))
        self.register(Action(
            "close_active_window", 2, tr("Closes the active window on the desktop."),
            {"type": "object", "properties": {}},
            lambda a: _close_active_window()))
        self.register(Action(
            "minimize_window", 2, tr("Minimizes the active window."),
            {"type": "object", "properties": {}},
            lambda a: _minimize_window()))
        self.register(Action(
            "maximize_window", 2, tr("Maximizes (or restores) the active window."),
            {"type": "object", "properties": {}},
            lambda a: _maximize_window()))
        self.register(Action(
            "list_windows", 1, tr("Lists open and minimized windows."),
            {"type": "object", "properties": {}},
            lambda a: _list_windows()))
        self.register(Action(
            "current_time", 1, tr("Tells the current time."),
            {"type": "object", "properties": {}},
            lambda a: _current_time()))
        self.register(Action(
            "current_date", 1, tr("Tells today's date."),
            {"type": "object", "properties": {}},
            lambda a: _current_date()))
        self.register(Action(
            "battery_status", 1, tr("Battery status."),
            {"type": "object", "properties": {}},
            lambda a: _battery_status()))
        self.register(Action(
            "volume_status", 1, tr("Current audio volume."),
            {"type": "object", "properties": {}},
            lambda a: _volume_status()))

        # LIVELLO 3 — configurazione (conferma richiesta)
        self.register(Action(
            "set_theme", 3, tr("Switches to the light or dark theme."),
            {"type": "object",
             "properties": {"tema": {"type": "string", "description": "chiaro (light) or scuro (dark)"}},
             "required": ["tema"]},
            _set_theme))
        self.register(Action(
            "set_accent", 3, tr("Changes the system accent color (#RRGGBB)."),
            {"type": "object",
             "properties": {"color": {"type": "string", "description": "#RRGGBB"}},
             "required": ["color"]},
            _set_accent))


# ------------------------------------------------------------------ helper

def _run(cmd: list[str], timeout: float = 15.0, env: dict | None = None) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return (p.stdout or p.stderr or "").strip()
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return tr("Command not available ({error}).").format(error=e)


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
    righe = [
        ("OS:", info.get("PRETTY_NAME", "ZETA RAYS OS")),
        (tr("Version:"), info.get("VERSION_ID", "2.0")),
        (tr("Architecture:"), platform.machine()),
        ("Kernel:", "Linux %s" % platform.release()),
        (tr("Environment:"), "ZETA RAYS Shell"),
    ]
    largo = max(15, max(len(k) for k, _v in righe) + 2)
    return "\n".join(k.ljust(largo) + v for k, v in righe)


def _security_status() -> str:
    # «systemctl is-active» stampa sempre active/inactive/failed in inglese
    fw = (_run(["systemctl", "is-active", "nftables"], env=_ENV_C).splitlines() or [""])[0].strip()
    stati = {"active": tr("active"), "inactive": tr("inactive"), "failed": tr("failed")}
    return tr("Firewall: {state}").format(state=stati.get(fw, fw or tr("unknown")))


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
        return ActionResult(False, tr("The search is taking too long: try a more specific name."))
    righe = []
    for riga in out.splitlines():
        try:
            t, tipo, percorso = riga.split("\t", 2)
            righe.append((float(t), tipo, percorso))
        except ValueError:
            continue
    oggi = bool(args.get("oggi"))
    giorni = args.get("giorni") if not oggi else None
    if not righe:
        if oggi:
            testo = tr("No “{pattern}” files modified today in your home folder.")
        elif giorni:
            testo = tr("No “{pattern}” files modified in the last {days} days in your home folder.")
        else:
            testo = tr("No “{pattern}” files in your home folder.")
        return ActionResult(True, testo.format(pattern=pattern, days=giorni))
    righe.sort(reverse=True)
    elenco = ["~" + p[len(casa):] + ("/" if tipo == "d" else "") for _t, tipo, p in righe[:40]]
    n = len(righe)
    if n > 40:
        if oggi:
            testa = tr("Found {n} files modified today, here are the 40 most recent:")
        elif giorni:
            testa = tr("Found {n} files modified in the last {days} days, here are the 40 most recent:")
        else:
            testa = tr("Found {n} files, here are the 40 most recent:")
    elif oggi:
        testa = ntr("Found {n} file modified today:", "Found {n} files modified today:", n)
    elif giorni:
        testa = ntr("Found {n} file modified in the last {days} days:",
                    "Found {n} files modified in the last {days} days:", n)
    else:
        testa = ntr("Found {n} file:", "Found {n} files:", n)
    return ActionResult(True, testa.format(n=n, days=giorni) + "\n" + "\n".join(elenco))


def _read_file(args: dict) -> ActionResult:
    p = _safe_path(args.get("path", ""))
    if p is None or not p.is_file():
        return ActionResult(False, tr("The file isn't accessible in the home folder."))
    try:
        text = p.read_text(errors="replace")[:8000]
        return ActionResult(True, text)
    except OSError as e:
        return ActionResult(False, tr("Couldn't read it: {error}").format(error=e))


# nomi comuni -> eseguibile reale
APP_ALIASES = {
    "browser": "firefox-esr", "internet": "firefox-esr", "web": "firefox-esr",
    "firefox": "firefox-esr", "navigatore": "firefox-esr", "web browser": "firefox-esr",
    "terminale": "foot", "terminal": "foot", "console": "foot", "shell": "foot",
    "file": "thunar", "files": "thunar", "cartelle": "thunar", "gestore file": "thunar",
    "file manager": "thunar", "folders": "thunar",
    "editor": "gnome-text-editor", "testo": "gnome-text-editor", "blocco note": "gnome-text-editor",
    "text editor": "gnome-text-editor", "notepad": "gnome-text-editor",
    "impostazioni": "zeta-impostazioni", "settings": "zeta-impostazioni", "preferenze": "zeta-impostazioni",
    "preferences": "zeta-impostazioni",
    "monitor": "zeta-monitor", "monitor di sistema": "zeta-monitor", "sistema": "zeta-monitor",
    "system monitor": "zeta-monitor", "task manager": "zeta-monitor",
    "sicurezza": "zeta-sicurezza", "security": "zeta-sicurezza",
    "calcolatrice": "gnome-calculator", "calcolatore": "gnome-calculator", "calculator": "gnome-calculator",
    "immagini": "eog", "foto": "eog", "documenti pdf": "evince", "pdf": "evince",
    "images": "eog", "photos": "eog", "pictures": "eog",
    "musica": "mpv", "video": "mpv", "pacchetti": "synaptic-pkexec",
    "music": "mpv", "videos": "mpv", "packages": "synaptic-pkexec",
    "core": "zeta-core", "assistente": "zeta-core", "assistant": "zeta-core",
}


def _resolve_app(app: str) -> str | None:
    key = app.strip().lower()
    cand = APP_ALIASES.get(key, app)
    if shutil.which(cand):
        return cand
    # prova anche l'eseguibile scritto così com'è
    return shutil.which(app)


def _launch(cmd: str, extra: list, label: str, aperto: str | None = None) -> ActionResult:
    exe = shutil.which(cmd)
    if not exe:
        return ActionResult(False, tr("{name} isn't available on this system.").format(name=label))
    try:
        _popen([exe] + [str(x) for x in extra], start_new_session=True)
        return ActionResult(True, aperto or tr("Opening {name}.").format(name=label))
    except OSError as e:
        return ActionResult(False, tr("Couldn't start {name}: {error}").format(name=label, error=e))


def _open_application(args: dict) -> ActionResult:
    app = args.get("app", "")
    exe = _resolve_app(app)
    if not exe:
        return ActionResult(False, tr("Can't find an app called “{name}”.").format(name=app))
    try:
        _popen([exe], start_new_session=True)
        return ActionResult(True, tr("Opening {name}.").format(name=app))
    except OSError as e:
        return ActionResult(False, tr("Couldn't start it: {error}").format(error=e))


# cartelle comuni -> directory reale (usa xdg-user-dir quando disponibile)
FOLDER_KEYS = {
    "documenti": "DOCUMENTS", "documents": "DOCUMENTS",
    "download": "DOWNLOAD", "scaricati": "DOWNLOAD", "downloads": "DOWNLOAD",
    "immagini": "PICTURES", "foto": "PICTURES", "pictures": "PICTURES",
    "photos": "PICTURES", "images": "PICTURES",
    "musica": "MUSIC", "music": "MUSIC",
    "video": "VIDEOS", "filmati": "VIDEOS", "videos": "VIDEOS",
    "scrivania": "DESKTOP", "desktop": "DESKTOP",
    "pubblici": "PUBLICSHARE", "modelli": "TEMPLATES",
    "public": "PUBLICSHARE", "templates": "TEMPLATES",
}


def _xdg_dir(key: str) -> str:
    out = _run(["xdg-user-dir", key], timeout=4)
    if out and os.path.isdir(out):
        return out
    return str(_home())


def _open_folder(args: dict) -> ActionResult:
    name = (args.get("name") or "").strip()
    low = name.lower()
    if low in ("", "home", "personale", "casa", "cartella personale", "home folder"):
        target = str(_home())
    elif low in ("cestino", "trash", "bin", "recycle bin"):
        # il cestino non e una cartella qualunque: il gestore file lo apre
        # come luogo speciale, da cui si possono ripristinare i file
        try:
            _popen(["thunar", "trash:///"], start_new_session=True)
            return ActionResult(True, tr("Opening the Trash."))
        except OSError as e:
            return ActionResult(False, tr("Couldn't open the Trash: {error}").format(error=e))
    elif low in FOLDER_KEYS:
        target = _xdg_dir(FOLDER_KEYS[low])
    else:
        p = _safe_path(name)
        target = str(p) if p and p.is_dir() else ""
    if not target or not os.path.isdir(target):
        return ActionResult(False, tr("Folder “{name}” not found.").format(name=name))
    fm = shutil.which("thunar") or shutil.which("xdg-open")
    if not fm:
        return ActionResult(False, tr("No file manager available."))
    try:
        _popen([fm, target], start_new_session=True)
        return ActionResult(True, tr("Opening the {name} folder.").format(
            name=os.path.basename(target.rstrip("/"))))
    except OSError as e:
        return ActionResult(False, tr("Couldn't open it: {error}").format(error=e))


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
        return ActionResult(False, tr("Failed: {error}").format(error=e))


def _semplice(cmd: list, messaggio: str) -> ActionResult:
    """Esegue un comando gia scritto qui dentro (non arriva dal modello)."""
    if not shutil.which(cmd[0]):
        return ActionResult(False, tr("Command not available: {command}").format(command=cmd[0]))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return ActionResult(False, tr("Failed: {error}").format(error=e))
    if r.returncode != 0:
        return ActionResult(False, (r.stderr or "").strip() or tr("Failed."))
    return ActionResult(True, messaggio)


def _set_volume(args: dict) -> ActionResult:
    # Passa da zeta-volume, lo stesso comando delle scorciatoie e della
    # rotella sulla barra: cosi l'icona del volume si aggiorna subito anche
    # quando e ZETA a cambiarlo, invece di aspettare la lettura periodica.
    if not shutil.which("zeta-volume"):
        return ActionResult(False, tr("Volume control isn't available."))
    if args.get("mute") is not None:
        # «muto» e un interruttore: si legge lo stato e si agisce solo se serve
        atteso = bool(args.get("mute"))
        try:
            letto = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                                   capture_output=True, text=True, timeout=5, env=_ENV_C).stdout
            gia_muto = "MUTED" in letto
        except Exception:
            gia_muto = not atteso
        if gia_muto != atteso:
            return _semplice(["zeta-volume", "muto"],
                             tr("Audio muted.") if atteso else tr("Audio unmuted."))
        return ActionResult(True, tr("Audio is already muted.") if atteso else tr("Audio is already on."))
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
        if args["step"] == "su":
            testo = tr("Volume up: now at {level}%.") if ora is not None else tr("Volume up.")
        else:
            testo = tr("Volume down: now at {level}%.") if ora is not None else tr("Volume down.")
        return ActionResult(True, testo.format(level=ora))
    try:
        livello = int(args.get("level", -1))
    except (TypeError, ValueError):
        return ActionResult(False, tr("Invalid level."))
    if not 0 <= livello <= 100:
        return ActionResult(False, tr("Volume goes from 0 to 100."))
    return _semplice(["zeta-volume", "imposta", str(livello)],
                     tr("Volume at {level}%.").format(level=livello))


def _volume_attuale():
    """Volume in percentuale (None se non leggibile)."""
    try:
        out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                             capture_output=True, text=True, timeout=5, env=_ENV_C).stdout
        return round(float(out.split()[1]) * 100)
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return None


def _set_brightness(args: dict) -> ActionResult:
    if not shutil.which("brightnessctl"):
        return ActionResult(False, tr("This screen doesn't support brightness control."))
    try:
        livello = int(args.get("level", -1))
    except (TypeError, ValueError):
        return ActionResult(False, tr("Invalid level."))
    if not 0 <= livello <= 100:
        return ActionResult(False, tr("Brightness goes from 0 to 100."))
    return _semplice(["brightnessctl", "set", "%d%%" % livello],
                     tr("Brightness at {level}%.").format(level=livello))


def _create_folder(args: dict) -> ActionResult:
    nome = (args.get("name") or "").strip()
    if not nome:
        return ActionResult(False, tr("What should it be called?"))
    p = _safe_path(nome)
    if p is None:
        return ActionResult(False, tr("I can only create folders inside your home folder."))
    if p.exists():
        return ActionResult(False, tr("“{name}” already exists.").format(name=p.name))
    try:
        p.mkdir(parents=True)
    except OSError as e:
        return ActionResult(False, tr("Failed: {error}").format(error=e))
    return ActionResult(True, tr("Created the folder {name}.").format(name=p.name))


def _trash_file(args: dict) -> ActionResult:
    nome = (args.get("name") or "").strip()
    p = _safe_path(nome) if nome else None
    if p is None or not p.exists():
        return ActionResult(False, tr("Can't find “{name}”.").format(name=nome))
    if not shutil.which("gio"):
        return ActionResult(False, tr("The Trash isn't available."))
    return _semplice(["gio", "trash", str(p)],
                     tr("“{name}” is in the Trash: you can still restore it.").format(name=p.name))


def _screen_off(args: dict) -> ActionResult:
    """Spegne lo schermo, senza bloccare la sessione.

    Non e' lo spegnimento del computer ne' il blocco: e' il monitor che si
    spegne e si riaccende al primo tasto. Serve a chi si allontana un momento.
    """
    if not shutil.which("hyprctl"):
        return ActionResult(False, tr("This isn't available outside the desktop."))
    r = subprocess.run(["hyprctl", "eval", 'hl.dsp.dpms({ action = "off" })'],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return ActionResult(False, (r.stderr or "").strip() or tr("Failed."))
    return ActionResult(True, tr("Screen off: press any key to turn it back on."))


def _rename_file(args: dict) -> ActionResult:
    """Rinomina un file o una cartella, senza spostarlo altrove.

    Il nome nuovo non puo' contenere percorsi: «../..» o «/etc/passwd» come
    nome nuovo sposterebbero il file fuori dalla cartella personale, che e'
    esattamente cio' che _safe_path serve a impedire.
    """
    nome = (args.get("name") or "").strip()
    nuovo = (args.get("new_name") or "").strip()
    if not nome or not nuovo:
        return ActionResult(False, tr("I need both the current name and the new one."))
    if "/" in nuovo or nuovo in (".", ".."):
        return ActionResult(False, tr("The new name can't contain paths."))
    p = _safe_path(nome)
    if p is None or not p.exists():
        return ActionResult(False, tr("Can't find “{name}”.").format(name=nome))
    dest = p.parent / nuovo
    if dest.exists():
        return ActionResult(False, tr("“{name}” already exists.").format(name=nuovo))
    try:
        p.rename(dest)
    except OSError as e:
        return ActionResult(False, tr("Failed: {error}").format(error=e))
    return ActionResult(True, tr("“{old}” is now called “{new}”.").format(old=p.name, new=nuovo))


def _move_file(args: dict) -> ActionResult:
    """Sposta un file o una cartella dentro un'altra cartella."""
    nome = (args.get("name") or "").strip()
    dove = (args.get("folder") or "").strip()
    if not nome or not dove:
        return ActionResult(False, tr("I need the file and the destination folder."))
    p = _safe_path(nome)
    low = dove.lower()
    if low in FOLDER_KEYS:
        d = Path(_xdg_dir(FOLDER_KEYS[low]))
    elif low in ("", "home", "personale", "casa", "home folder"):
        d = _home()
    else:
        d = _safe_path(dove)
    if p is None or not p.exists():
        return ActionResult(False, tr("Can't find “{name}”.").format(name=nome))
    if d is None or not d.is_dir():
        return ActionResult(False, tr("“{name}” isn't a folder.").format(name=dove))
    dest = d / p.name
    if dest.exists():
        return ActionResult(False, tr("“{folder}” already contains “{name}”.").format(
            folder=d.name, name=p.name))
    try:
        shutil.move(str(p), str(dest))
    except (OSError, shutil.Error) as e:
        return ActionResult(False, tr("Failed: {error}").format(error=e))
    return ActionResult(True, tr("Moved “{name}” to {folder}.").format(name=p.name, folder=d.name))


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
        return ActionResult(False, tr("The screenshot tool isn't available."))
    # la cartella Immagini ha un nome diverso in ogni lingua (Pictures...):
    # si chiede a xdg-user-dir, come per le altre cartelle
    cartella = Path(_xdg_dir("PICTURES"))
    if cartella == _home():
        cartella = _home() / "Immagini"
    cartella.mkdir(parents=True, exist_ok=True)
    dest = cartella / (tr("screenshot-{time}.png").format(time=time.strftime("%Y%m%d-%H%M%S")))
    # Con un limite di tempo: se il compositore non risponde alla richiesta di
    # copia dello schermo, meglio un messaggio dopo dodici secondi che una
    # finestra ferma per sempre.
    try:
        r = subprocess.run(["grim", str(dest)], capture_output=True, text=True, timeout=12)
    except subprocess.TimeoutExpired:
        return ActionResult(False, tr("The screenshot wasn't taken in time: "
                                      "the compositor didn't respond."))
    if r.returncode != 0 or not dest.exists():
        return ActionResult(False, (r.stderr or "").strip() or tr("Screenshot failed."))
    return ActionResult(True, tr("Screenshot saved in {folder}: {name}").format(
        folder=cartella.name, name=dest.name))


def _search_content(args: dict) -> ActionResult:
    """Cerca una parola DENTRO i file, non solo nei nomi.

    Usa l'indice di zeta-cerca, che legge anche il testo dei PDF e quello
    riconosciuto nelle immagini: e' l'unico modo per trovare «la fattura di
    marzo» quando il file si chiama «scan_0012.pdf».
    """
    testo = (args.get("text") or "").strip()
    if not testo:
        return ActionResult(False, tr("What should I search for?"))
    if not shutil.which("zeta-index"):
        return ActionResult(False, tr("Content search isn't available."))
    try:
        r = subprocess.run(["zeta-index", "cerca", testo], capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return ActionResult(False, tr("Search failed: {error}").format(error=e))
    righe = [x for x in (r.stdout or "").splitlines() if x.strip()][:15]
    if not righe:
        return ActionResult(True, tr("No file contains “{text}”.").format(text=testo))
    return ActionResult(True, ntr("Found in {n} file:", "Found in {n} files:", len(righe)).format(
        n=len(righe)) + "\n" + "\n".join(righe))


def _pacchetto(azione: str, args: dict) -> ActionResult:
    nome = (args.get("name") or "").strip()
    if not nome or not all(c.isalnum() or c in ".+-" for c in nome):
        return ActionResult(False, tr("Invalid program name."))
    if not shutil.which("pkexec"):
        return ActionResult(False, tr("I can't ask for administrator permissions."))
    fatto = tr("Installed {name}.") if azione == "install" else tr("Removed {name}.")
    return _semplice(["pkexec", "apt-get", "-y", azione, nome], fatto.format(name=nome))


def _propose_command(args: dict) -> ActionResult:
    """Prepara un comando per l utente: negli appunti e con il terminale aperto.

    Non esegue nulla. E il modo di dire «so cosa serve, eccolo» lasciando la
    decisione a chi sta davanti allo schermo.
    """
    comando = (args.get("command") or "").strip()
    if not comando:
        return ActionResult(False, tr("No command to suggest."))
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
    testo = tr("You need this command:") + "\n\n    %s\n" % comando
    if perche:
        testo += "\n(%s)\n" % perche
    testo += "\n" + (tr("I copied it to the clipboard and opened the terminal: paste it "
                        "with Ctrl+Shift+V and press Enter.") if copiato
                     else tr("I opened the terminal: type it there and press Enter."))
    return ActionResult(True, testo)


def _open_file(args: dict) -> ActionResult:
    """Apre un file con il programma predefinito del sistema.

    Il percorso resta confinato nella cartella personale, come per le
    cartelle: ZETA non deve poter aprire file di sistema a comando.
    """
    nome = (args.get("name") or "").strip()
    if not nome:
        return ActionResult(False, tr("Which file?"))
    p = _safe_path(nome)
    if p is None or not p.is_file():
        # non è un percorso: si cerca per nome nella cartella personale
        trovati = _run(["sh", "-c",
                        "find %s -maxdepth 6 -iname %s -type f 2>/dev/null | head -n 5"
                        % (shlex.quote(str(_home())), shlex.quote("*%s*" % nome))])
        righe = [r for r in trovati.splitlines() if r.strip()]
        if not righe:
            return ActionResult(False, tr("Can't find any file called “{name}”.").format(name=nome))
        if len(righe) > 1:
            elenco = "\n".join("  " + os.path.relpath(r, str(_home())) for r in righe)
            return ActionResult(False, tr("There's more than one, tell me which:") + "\n" + elenco)
        p = Path(righe[0])
    apri = shutil.which("gio") or shutil.which("xdg-open")
    if not apri:
        return ActionResult(False, tr("No app available to open files."))
    cmd = [apri, "open", str(p)] if os.path.basename(apri) == "gio" else [apri, str(p)]
    try:
        _popen(cmd, start_new_session=True)
        return ActionResult(True, tr("Opening {name}.").format(name=p.name))
    except OSError as e:
        return ActionResult(False, tr("Couldn't open it: {error}").format(error=e))


def _open_url(args: dict) -> ActionResult:
    """Apre un indirizzo nel navigatore.

    Solo http e https: altri schemi (file://, comandi, percorsi locali) non
    passano di qui, altrimenti ZETA diventerebbe un modo per far
    aprire al sistema qualunque cosa.
    """
    url = (args.get("url") or "").strip()
    if not url:
        return ActionResult(False, tr("Which address?"))
    if "://" not in url:
        url = "https://" + url
    if not url.lower().startswith(("http://", "https://")):
        return ActionResult(False, tr("I can only open web addresses (http or https)."))
    browser = shutil.which("firefox-esr") or shutil.which("firefox") or shutil.which("xdg-open")
    if not browser:
        return ActionResult(False, tr("No browser available."))
    try:
        _popen([browser, url], start_new_session=True)
        return ActionResult(True, tr("Opening {url} in the browser.").format(url=url))
    except OSError as e:
        return ActionResult(False, tr("Couldn't open it: {error}").format(error=e))


def _set_wallpaper(args: dict) -> ActionResult:
    """Cambia lo sfondo, o torna a quello generato da ZETA RAYS."""
    nome = (args.get("name") or "").strip()
    if not shutil.which("zeta-sfondo"):
        return ActionResult(False, tr("The wallpaper command isn't available."))
    if not nome or nome.lower() in ("predefinito", "default", "zeta", "zeta rays", "originale", "original"):
        r = _run(["zeta-sfondo", "reset"])
        return ActionResult(True, tr("Restored the ZETA RAYS wallpaper.") + (" " + r if r else ""))
    from system import sfondi
    ufficiale = sfondi.cerca(nome)
    if ufficiale:
        _run(["zeta-sfondo", "set", ufficiale])
        # si dice «fatto» solo se zeta-sfondo conferma davvero la scelta
        if _run(["zeta-sfondo", "get"]).split("\n")[0].strip() != ufficiale:
            return ActionResult(False, tr("I couldn't change the wallpaper."))
        return ActionResult(True, tr("Wallpaper changed: {name}.").format(name=sfondi.nome_di(ufficiale)))
    p = _safe_path(nome)
    if p is None or not p.is_file():
        return ActionResult(False, tr("Can't find the image “{name}”.").format(name=nome))
    r = _run(["zeta-sfondo", "set", str(p)])
    return ActionResult(True, tr("Wallpaper changed to {name}.").format(name=p.name) + (" " + r if r else ""))


SETTINGS_PAGES = {"aspetto", "rete", "bluetooth", "audio", "ai", "sicurezza", "pacchetti", "informazioni"}
SETTINGS_ALIASES = {"wifi": "rete", "wi-fi": "rete", "network": "rete", "suono": "audio",
                    "intelligenza": "ai", "assistente": "ai", "tema": "aspetto", "colore": "aspetto",
                    "info": "informazioni", "sistema": "informazioni",
                    "appearance": "aspetto", "theme": "aspetto", "color": "aspetto", "wallpaper": "aspetto",
                    "sound": "audio", "assistant": "ai", "security": "sicurezza",
                    "packages": "pacchetti", "about": "informazioni", "system": "informazioni"}


def nome_pagina(page: str) -> str:
    """Nome mostrato di una pagina delle Impostazioni (la chiave resta italiana)."""
    nomi = {"aspetto": tr("Appearance"), "rete": tr("Network"), "bluetooth": "Bluetooth",
            "audio": tr("Sound"), "ai": "AI", "sicurezza": tr("Security"),
            "pacchetti": tr("Packages"), "informazioni": tr("About")}
    return nomi.get(page, page)


def _open_settings(args: dict) -> ActionResult:
    exe = shutil.which("zeta-impostazioni")
    if not exe:
        return ActionResult(False, tr("Settings isn't available."))
    page = (args.get("page") or "").strip().lower()
    page = SETTINGS_ALIASES.get(page, page)
    cmd = [exe] + ([page] if page in SETTINGS_PAGES else [])
    try:
        _popen(cmd, start_new_session=True)
        if page in SETTINGS_PAGES:
            return ActionResult(True, tr("Opening Settings › {page}.").format(page=nome_pagina(page)))
        return ActionResult(True, tr("Opening Settings."))
    except OSError as e:
        return ActionResult(False, tr("Couldn't open Settings: {error}").format(error=e))


_GIORNI = (tr("Monday"), tr("Tuesday"), tr("Wednesday"), tr("Thursday"), tr("Friday"),
           tr("Saturday"), tr("Sunday"))
_MESI = (tr("January"), tr("February"), tr("March"), tr("April"), tr("May"), tr("June"),
         tr("July"), tr("August"), tr("September"), tr("October"), tr("November"), tr("December"))


def _current_time() -> ActionResult:
    import datetime
    ora = datetime.datetime.now()
    return ActionResult(True, tr("It's {time}.").format(time=ora.strftime("%H:%M")))


def _current_date() -> ActionResult:
    import datetime
    o = datetime.date.today()
    return ActionResult(True, tr("Today is {weekday}, {month} {day}, {year}.").format(
        weekday=_GIORNI[o.weekday()], day=o.day, month=_MESI[o.month - 1], year=o.year))


def _battery_status() -> ActionResult:
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import power
    b = power.battery()
    if not b:
        return ActionResult(True, tr("This computer doesn't have a battery."))
    stato = b.get("state") or ""
    if stato:
        return ActionResult(True, tr("Battery at {percent}% — {state}.").format(
            percent=b.get("percent", "?"), state=stato))
    return ActionResult(True, tr("Battery at {percent}%.").format(percent=b.get("percent", "?")))


def _volume_status() -> ActionResult:
    out = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=4, env=_ENV_C)
    if not out or "Volume" not in out:
        return ActionResult(False, tr("I can't read the volume."))
    muto = "MUTED" in out
    try:
        valore = float(out.split()[1])
    except (IndexError, ValueError):
        return ActionResult(False, tr("I can't read the volume."))
    testo = tr("Volume at {level}% (muted).") if muto else tr("Volume at {level}%.")
    return ActionResult(True, testo.format(level=round(valore * 100)))


def _windows():
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import windows
    return windows


def _minimize_window() -> ActionResult:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ActionResult(False, tr("No desktop session is running."))
    if _windows().minimize():
        return ActionResult(True, tr("Done: you'll find it in the bar, under “minimized”."))
    return ActionResult(False, tr("There's no window to minimize."))


def _maximize_window() -> ActionResult:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ActionResult(False, tr("No desktop session is running."))
    if _windows().toggle_maximize():
        return ActionResult(True, tr("I maximized the active window."))
    return ActionResult(False, tr("I couldn't maximize the window."))


def _list_windows() -> ActionResult:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ActionResult(False, tr("No desktop session is running."))
    w = _windows()
    aperte = w.open_windows()
    ridotte = w.minimized()
    nessuna = "  " + tr("(none)")
    righe = [tr("Open windows:")]
    righe += ["  • " + tr("{title} (workspace {n})").format(title=x["title"][:50], n=x["workspace"])
              for x in aperte] or [nessuna]
    righe.append(tr("Minimized:"))
    righe += ["  • %s" % x["title"][:50] for x in ridotte] or [nessuna]
    return ActionResult(True, "\n".join(righe))


def _set_theme(args: dict) -> ActionResult:
    tema = (args.get("tema") or "").strip().lower()
    tema = {"light": "chiaro", "dark": "scuro"}.get(tema, tema)
    if tema not in ("chiaro", "scuro"):
        return ActionResult(False, tr("Invalid theme: use “light” or “dark”."))
    p = subprocess.run(["zeta-aspetto", "set", "tema", tema],
                       capture_output=True, text=True)
    if p.returncode == 0:
        return ActionResult(True, tr("Light theme applied.") if tema == "chiaro"
                            else tr("Dark theme applied."))
    return ActionResult(False, tr("I couldn't change the theme."))


def _close_active_window() -> ActionResult:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ActionResult(False, tr("No desktop session is running."))
    # Hyprland di ZETA RAYS usa i dispatcher Lua: la forma classica non funziona.
    p = subprocess.run(["hyprctl", "dispatch", "hl.dsp.window.close()"],
                       capture_output=True, text=True)
    if p.returncode == 0 and "ok" in (p.stdout or "").lower():
        return ActionResult(True, tr("I closed the active window."))
    return ActionResult(False, tr("I couldn't close the window."))


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
        return tr("CPU usage: {percent}%").format(percent="%.0f" % pct)
    except (OSError, ValueError, IndexError):
        return tr("I can't read the CPU usage.")


def _memory_usage() -> str:
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k] = float(v.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return tr("I can't read the memory usage.")
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", 0)
    used = total - avail
    g = 1024 ** 3
    pct = 100 * used / total if total else 0
    return tr("Memory: {used} GB of {total} GB in use ({percent}%), {free} GB free.").format(
        used="%.1f" % (used / g), total="%.1f" % (total / g), percent="%.0f" % pct,
        free="%.1f" % (avail / g))


def _ip_address() -> str:
    out = _run(["sh", "-c",
                "ip -brief -4 addr show scope global 2>/dev/null | awk '{print $1\": \"$3}'"])
    return out or tr("No active IP address.")


def _list_applications() -> str:
    """Le app del menu (registro unico: anche Flatpak e AppImage)."""
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import applicazioni
    nomi = [a.nome for a in applicazioni.menu()]
    return tr("Available apps:") + "\n" + ", ".join(nomi[:60]) if nomi else tr("No apps found.")


def _set_accent(args: dict) -> ActionResult:
    color = args.get("color", "")
    exe = shutil.which("zeta-accent")
    if not exe:
        return ActionResult(False, tr("The {command} command isn't available.").format(command="zeta-accent"))
    p = subprocess.run([exe, color], capture_output=True, text=True)
    if p.returncode == 0:
        return ActionResult(True, tr("Accent color set to {color}.").format(color=color))
    return ActionResult(False, (p.stderr or tr("Invalid color.")).strip())
