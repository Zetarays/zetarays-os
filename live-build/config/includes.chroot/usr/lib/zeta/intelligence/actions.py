# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — action engine (allowlist + permission levels).

The AI does not run arbitrary shell commands. It can only request the actions
defined here, each with a permission level:

  LEVEL 0  conversation
  LEVEL 1  reading system information
  LEVEL 2  user actions on apps/files
  LEVEL 3  system configuration          -> requires confirmation
  LEVEL 4  administrative/root actions   -> requires confirmation

Every requested action is logged in ~/.local/share/zeta/actions.log.
Level 3 and 4 actions first return a preview; they are executed only after
explicit authorization.
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
    """Popen that waits for the program to finish in the background (no
    zombies in the ZETA process, which stays open)."""
    import threading
    p = subprocess.Popen(*a, **kw)
    threading.Thread(target=p.wait, daemon=True).start()
    return p


LOG_FILE = Path(os.path.expanduser("~/.local/share/zeta/actions.log"))

# wpctl prints the volume with the locale's decimal separator (0,40 in
# Italian): to parse it we always ask for the C form (0.40)
_ENV_C = dict(os.environ, LC_ALL="C")


@dataclass
class ActionResult:
    ok: bool
    output: str
    # if confirmation is needed, the action has not been executed yet:
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

    # --- registration ---
    def register(self, action: Action) -> None:
        self.actions[action.name] = action

    def tool_specs(self) -> list[ToolSpec]:
        return [ToolSpec(name=a.name, description=a.description, schema=a.schema)
                for a in self.actions.values()]

    # --- execution ---
    def run(self, name: str, args: dict, *, authorized: bool = False) -> ActionResult:
        action = self.actions.get(name)
        if action is None:
            return ActionResult(False, tr("Unknown action: {name}").format(name=name))
        self._log(name, args, action.level)
        # levels 3/4: first the preview, then the authorized execution
        if action.level >= 3 and not authorized:
            preview, impact = self._preview(action, args)
            return ActionResult(True, "", needs_confirmation=True,
                                preview=preview, impact=impact, level=action.level)
        try:
            return action.handler(args)
        except Exception as e:  # noqa: BLE001 — never bring ZETA down
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
                LOG_FILE.replace(LOG_FILE.with_name(LOG_FILE.name + ".1"))   # keep it short
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    "action": name, "level": level, "args": args},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass

    # --- built-in actions ---
    def _register_builtin(self) -> None:
        # LEVEL 1 — read only
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
                            "today": {"type": "boolean", "description": "only files modified today"},
                            "days": {"type": "integer", "description": "only files modified in the last N days"}},
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

        # LEVEL 2 — user actions
        self.register(Action(
            "open_application", 2, tr("Opens an installed app (common name or executable)."),
            {"type": "object",
             "properties": {"app": {"type": "string"}},
             "required": ["app"]},
            _open_application))
        self.register(Action(
            "open_folder", 2, tr("Opens a folder in the file manager (e.g. documents, downloads, pictures, or a path)."),
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "documents, downloads, pictures, music, videos, desktop, home, trash, or a path"}},
             "required": ["name"]},
            _open_folder))
        self.register(Action(
            "open_settings", 2, tr("Opens ZETA RAYS Settings, optionally on a specific page."),
            {"type": "object",
             "properties": {"page": {"type": "string", "description": "page key: appearance, network, bluetooth, audio, ai, security, packages, info (about)"}}},
            _open_settings))
        self.register(Action(
            "open_system_monitor", 2, tr("Opens the ZETA RAYS System Monitor (CPU, network, processes, firewall…)."),
            {"type": "object", "properties": {"section": {"type": "string"}}},
            lambda a: _launch("zeta-monitor", [a["section"]] if a.get("section") else [],
                              tr("System Monitor"))))
        self.register(Action(
            "open_security", 2, tr("Opens ZETA RAYS Security (firewall, security tools, system status)."),
            {"type": "object", "properties": {}},
            lambda a: _launch("zeta-security", [], "ZETA RAYS Security")))
        # When none of the actions above is enough, ZETA does not give up: it
        # writes the command that would be needed, puts it in the clipboard
        # and opens the terminal. You are the one who presses Enter. This way
        # ZETA can help with anything without a one-billion-parameter model
        # being able to do something irreversible on its own.
        # --- power: level 3, because they interrupt the user's work ---
        self.register(Action(
            "lock_screen", 2, tr("Locks the screen."),
            {"type": "object", "properties": {}},
            lambda a: _power_action("lock", tr("Locking the screen."))))
        self.register(Action(
            "log_out", 3, tr("Ends the session and returns to the login screen."),
            {"type": "object", "properties": {}},
            lambda a: _power_action("logout", tr("Logging out."))))
        self.register(Action(
            "suspend", 3, tr("Suspends the computer."),
            {"type": "object", "properties": {}},
            lambda a: _power_action("suspend", tr("Suspending the computer."))))
        self.register(Action(
            "reboot", 4, tr("Restarts the computer."),
            {"type": "object", "properties": {}},
            lambda a: _simple(["systemctl", "reboot"], tr("Restarting."))))
        self.register(Action(
            "power_off", 4, tr("Shuts down the computer."),
            {"type": "object", "properties": {}},
            lambda a: _simple(["systemctl", "poweroff"], tr("Shutting down."))))

        # --- sound and screen ---
        self.register(Action(
            "set_volume", 2, tr("Sets the volume (0-100), raises or lowers it by a step, or mutes it."),
            {"type": "object",
             "properties": {"level": {"type": "integer", "description": "from 0 to 100"},
                            "step": {"type": "string", "enum": ["up", "down"],
                                     "description": "up or down, relative to the current volume"},
                            "amount": {"type": "integer", "description": "by how many points (default 10)"},
                            "mute": {"type": "boolean"}}},
            _set_volume))
        self.register(Action(
            "set_brightness", 2, tr("Sets the screen brightness (0-100)."),
            {"type": "object",
             "properties": {"level": {"type": "integer", "description": "from 0 to 100"}},
             "required": ["level"]},
            _set_brightness))

        # --- files and folders ---
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
            lambda a: _simple(["sh", "-c", "gio trash --empty"], tr("Trash emptied."))))

        # --- programs ---
        self.register(Action(
            "install_package", 4, tr("Installs a program from the system repositories."),
            {"type": "object",
             "properties": {"name": {"type": "string"}},
             "required": ["name"]},
            lambda a: _package("install", a)))
        self.register(Action(
            "remove_package", 4, tr("Removes an installed program."),
            {"type": "object",
             "properties": {"name": {"type": "string"}},
             "required": ["name"]},
            lambda a: _package("remove", a)))

        # --- network ---
        self.register(Action(
            "wifi_toggle", 3, tr("Turns Wi-Fi on or off."),
            {"type": "object",
             "properties": {"on": {"type": "boolean"}},
             "required": ["on"]},
            lambda a: _simple(["nmcli", "radio", "wifi", "on" if a.get("on") else "off"],
                                tr("Wi-Fi on.") if a.get("on") else tr("Wi-Fi off."))))

        # No «run any command» action: there was one (level 4, with
        # confirmation and even as administrator) and it goes against a
        # ZETA RAYS rule: the AI never has free access to the system, let
        # alone as root. When no action is enough, ZETA prepares the command
        # in the terminal and leaves the decision to whoever sits at the screen.
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
                                     "description": "path of the image, or «default» to go back to the ZETA RAYS one"}}},
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

        # LEVEL 3 — configuration (confirmation required)
        self.register(Action(
            "set_theme", 3, tr("Switches to the light or dark theme."),
            {"type": "object",
             "properties": {"theme": {"type": "string", "description": "light or dark"}},
             "required": ["theme"]},
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
    lines = [
        ("OS:", info.get("PRETTY_NAME", "ZETA RAYS OS")),
        (tr("Version:"), info.get("VERSION_ID", "2.0")),
        (tr("Architecture:"), platform.machine()),
        ("Kernel:", "Linux %s" % platform.release()),
        (tr("Environment:"), "ZETA RAYS Shell"),
    ]
    width = max(15, max(len(k) for k, _v in lines) + 2)
    return "\n".join(k.ljust(width) + v for k, v in lines)


def _security_status() -> str:
    # «systemctl is-active» always prints active/inactive/failed in English
    fw = (_run(["systemctl", "is-active", "nftables"], env=_ENV_C).splitlines() or [""])[0].strip()
    states = {"active": tr("active"), "inactive": tr("inactive"), "failed": tr("failed")}
    return tr("Firewall: {state}").format(state=states.get(fw, fw or tr("unknown")))


def _home() -> Path:
    return Path(os.path.expanduser("~")).resolve()


def _safe_path(raw: str) -> Path | None:
    """Confines a path to the home folder (no '..' or absolute paths outside it)."""
    p = (_home() / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
    return p if str(p).startswith(str(_home())) else None


def _find_files(args: dict) -> ActionResult:
    """Searches the home folder, most recent first.

    Hidden folders (.cache, .config, .local...) are left out: previously
    «cerca i png» returned the cached thumbnails instead of the photos.
    The command is passed as a list of arguments, without a shell.
    """
    pattern = (args.get("pattern") or "*").strip() or "*"
    home = str(_home())
    cmd = ["find", home, "-maxdepth", "8"]
    if args.get("today"):
        cmd.append("-daystart")          # «today» = since midnight, not «last 24 hours»
    # several comma-separated extensions: «*.jpg,*.png» = either one
    names = [p.strip() for p in pattern.split(",") if p.strip()] or ["*"]
    cmd += ["-not", "-path", "*/.*", "("]
    for i, name in enumerate(names):
        cmd += (["-o"] if i else []) + ["-iname", name]
    cmd += [")"]
    if args.get("today"):
        cmd += ["-mtime", "0"]
    else:
        try:
            days = int(args.get("days") or 0)
        except (TypeError, ValueError):
            days = 0
        if days > 0:
            cmd += ["-mtime", "-%d" % days]
    cmd += ["-printf", "%T@\t%y\t%p\n"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except subprocess.TimeoutExpired:
        return ActionResult(False, tr("The search is taking too long: try a more specific name."))
    lines = []
    for line in out.splitlines():
        try:
            t, kind, path = line.split("\t", 2)
            lines.append((float(t), kind, path))
        except ValueError:
            continue
    today = bool(args.get("today"))
    days = args.get("days") if not today else None
    if not lines:
        if today:
            text = tr("No “{pattern}” files modified today in your home folder.")
        elif days:
            text = tr("No “{pattern}” files modified in the last {days} days in your home folder.")
        else:
            text = tr("No “{pattern}” files in your home folder.")
        return ActionResult(True, text.format(pattern=pattern, days=days))
    lines.sort(reverse=True)
    listing = ["~" + p[len(home):] + ("/" if kind == "d" else "") for _t, kind, p in lines[:40]]
    n = len(lines)
    if n > 40:
        if today:
            header = tr("Found {n} files modified today, here are the 40 most recent:")
        elif days:
            header = tr("Found {n} files modified in the last {days} days, here are the 40 most recent:")
        else:
            header = tr("Found {n} files, here are the 40 most recent:")
    elif today:
        header = ntr("Found {n} file modified today:", "Found {n} files modified today:", n)
    elif days:
        header = ntr("Found {n} file modified in the last {days} days:",
                    "Found {n} files modified in the last {days} days:", n)
    else:
        header = ntr("Found {n} file:", "Found {n} files:", n)
    return ActionResult(True, header.format(n=n, days=days) + "\n" + "\n".join(listing))


def _read_file(args: dict) -> ActionResult:
    p = _safe_path(args.get("path", ""))
    if p is None or not p.is_file():
        return ActionResult(False, tr("The file isn't accessible in the home folder."))
    try:
        text = p.read_text(errors="replace")[:8000]
        return ActionResult(True, text)
    except OSError as e:
        return ActionResult(False, tr("Couldn't read it: {error}").format(error=e))


# common names -> actual executable
# i18n-data-begin: Italian and English app names
APP_ALIASES = {
    "browser": "firefox-esr", "internet": "firefox-esr", "web": "firefox-esr",
    "firefox": "firefox-esr", "navigatore": "firefox-esr", "web browser": "firefox-esr",
    "terminale": "foot", "terminal": "foot", "console": "foot", "shell": "foot",
    "file": "thunar", "files": "thunar", "cartelle": "thunar", "gestore file": "thunar",
    "file manager": "thunar", "folders": "thunar",
    "editor": "gnome-text-editor", "testo": "gnome-text-editor", "blocco note": "gnome-text-editor",
    "text editor": "gnome-text-editor", "notepad": "gnome-text-editor",
    "impostazioni": "zeta-settings", "settings": "zeta-settings", "preferenze": "zeta-settings",
    "preferences": "zeta-settings",
    "monitor": "zeta-monitor", "monitor di sistema": "zeta-monitor", "sistema": "zeta-monitor",
    "system monitor": "zeta-monitor", "task manager": "zeta-monitor",
    "sicurezza": "zeta-security", "security": "zeta-security",
    "calcolatrice": "gnome-calculator", "calcolatore": "gnome-calculator", "calculator": "gnome-calculator",
    "immagini": "eog", "foto": "eog", "documenti pdf": "evince", "pdf": "evince",
    "images": "eog", "photos": "eog", "pictures": "eog",
    "musica": "mpv", "video": "mpv", "pacchetti": "synaptic-pkexec",
    "music": "mpv", "videos": "mpv", "packages": "synaptic-pkexec",
    "core": "zeta-core", "assistente": "zeta-core", "assistant": "zeta-core",
}
# i18n-data-end


def _resolve_app(app: str) -> str | None:
    key = app.strip().lower()
    cand = APP_ALIASES.get(key, app)
    if shutil.which(cand):
        return cand
    # also try the executable exactly as written
    return shutil.which(app)


def _launch(cmd: str, extra: list, label: str, opened: str | None = None) -> ActionResult:
    exe = shutil.which(cmd)
    if not exe:
        return ActionResult(False, tr("{name} isn't available on this system.").format(name=label))
    try:
        _popen([exe] + [str(x) for x in extra], start_new_session=True)
        return ActionResult(True, opened or tr("Opening {name}.").format(name=label))
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


# common folders -> actual directory (uses xdg-user-dir when available)
# i18n-data-begin: Italian and English folder names
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
# i18n-data-end


def _xdg_dir(key: str) -> str:
    out = _run(["xdg-user-dir", key], timeout=4)
    if out and os.path.isdir(out):
        return out
    return str(_home())


def _open_folder(args: dict) -> ActionResult:
    name = (args.get("name") or "").strip()
    low = name.lower()
    if low in ("", "home", "personale", "casa", "cartella personale", "home folder"):  # i18n-data
        target = str(_home())
    elif low in ("cestino", "trash", "bin", "recycle bin"):  # i18n-data
        # the Trash is not an ordinary folder: the file manager opens it as a
        # special location, from which files can be restored
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


def _power_action(operation: str, message: str) -> ActionResult:
    """Lock, suspend, log out: they go through the power module, which knows
    how to really do it (hyprlock, hl.dsp.exit, systemctl), instead of a
    made-up command that would not exist."""
    try:
        import sys
        sys.path.insert(0, "/usr/lib/zeta")
        from system import power
        getattr(power, operation)()
        return ActionResult(True, message)
    except Exception as e:  # noqa: BLE001
        return ActionResult(False, tr("Failed: {error}").format(error=e))


def _simple(cmd: list, message: str) -> ActionResult:
    """Runs a command written here in the code (it does not come from the model)."""
    if not shutil.which(cmd[0]):
        return ActionResult(False, tr("Command not available: {command}").format(command=cmd[0]))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return ActionResult(False, tr("Failed: {error}").format(error=e))
    if r.returncode != 0:
        return ActionResult(False, (r.stderr or "").strip() or tr("Failed."))
    return ActionResult(True, message)


def _set_volume(args: dict) -> ActionResult:
    # Goes through zeta-volume, the same command used by the shortcuts and
    # the scroll wheel on the bar: this way the volume icon updates right
    # away even when ZETA changes it, instead of waiting for the periodic read.
    if not shutil.which("zeta-volume"):
        return ActionResult(False, tr("Volume control isn't available."))
    if args.get("mute") is not None:
        # «mute» is a toggle: read the state and act only if needed
        expected_value = bool(args.get("mute"))
        try:
            volume_output = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                                   capture_output=True, text=True, timeout=5, env=_ENV_C).stdout
            already_muted = "MUTED" in volume_output
        except Exception:
            already_muted = not expected_value
        if already_muted != expected_value:
            return _simple(["zeta-volume", "mute"],
                             tr("Audio muted.") if expected_value else tr("Audio unmuted."))
        return ActionResult(True, tr("Audio is already muted.") if expected_value else tr("Audio is already on."))
    if args.get("step") in ("up", "down"):
        # «alza il volume» is relative: previously it always set it to 80%,
        # so from 95 «raise» actually lowered it.
        try:
            amount = max(1, min(50, int(args.get("amount") or 10)))
        except (TypeError, ValueError):
            amount = 10
        r = _simple(["zeta-volume", args["step"], str(amount)], "")
        if not r.ok:
            return r
        now = _current_volume()
        if args["step"] == "up":
            text = tr("Volume up: now at {level}%.") if now is not None else tr("Volume up.")
        else:
            text = tr("Volume down: now at {level}%.") if now is not None else tr("Volume down.")
        return ActionResult(True, text.format(level=now))
    try:
        level = int(args.get("level", -1))
    except (TypeError, ValueError):
        return ActionResult(False, tr("Invalid level."))
    if not 0 <= level <= 100:
        return ActionResult(False, tr("Volume goes from 0 to 100."))
    return _simple(["zeta-volume", "set", str(level)],
                     tr("Volume at {level}%.").format(level=level))


def _current_volume():
    """Volume as a percentage (None if it cannot be read)."""
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
        level = int(args.get("level", -1))
    except (TypeError, ValueError):
        return ActionResult(False, tr("Invalid level."))
    if not 0 <= level <= 100:
        return ActionResult(False, tr("Brightness goes from 0 to 100."))
    return _simple(["brightnessctl", "set", "%d%%" % level],
                     tr("Brightness at {level}%.").format(level=level))


def _create_folder(args: dict) -> ActionResult:
    name = (args.get("name") or "").strip()
    if not name:
        return ActionResult(False, tr("What should it be called?"))
    p = _safe_path(name)
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
    name = (args.get("name") or "").strip()
    p = _safe_path(name) if name else None
    if p is None or not p.exists():
        return ActionResult(False, tr("Can't find “{name}”.").format(name=name))
    if not shutil.which("gio"):
        return ActionResult(False, tr("The Trash isn't available."))
    return _simple(["gio", "trash", str(p)],
                     tr("“{name}” is in the Trash: you can still restore it.").format(name=p.name))


def _screen_off(args: dict) -> ActionResult:
    """Turns off the screen, without locking the session.

    It is neither shutting down the computer nor locking it: the monitor
    turns off and comes back on at the first key press. Useful for stepping
    away for a moment.
    """
    if not shutil.which("hyprctl"):
        return ActionResult(False, tr("This isn't available outside the desktop."))
    r = subprocess.run(["hyprctl", "eval", 'hl.dsp.dpms({ action = "off" })'],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return ActionResult(False, (r.stderr or "").strip() or tr("Failed."))
    return ActionResult(True, tr("Screen off: press any key to turn it back on."))


def _rename_file(args: dict) -> ActionResult:
    """Renames a file or folder, without moving it elsewhere.

    The new name cannot contain paths: «../..» or «/etc/passwd» as the new
    name would move the file out of the home folder, which is exactly what
    _safe_path is there to prevent.
    """
    name = (args.get("name") or "").strip()
    new = (args.get("new_name") or "").strip()
    if not name or not new:
        return ActionResult(False, tr("I need both the current name and the new one."))
    if "/" in new or new in (".", ".."):
        return ActionResult(False, tr("The new name can't contain paths."))
    p = _safe_path(name)
    if p is None or not p.exists():
        return ActionResult(False, tr("Can't find “{name}”.").format(name=name))
    dest = p.parent / new
    if dest.exists():
        return ActionResult(False, tr("“{name}” already exists.").format(name=new))
    try:
        p.rename(dest)
    except OSError as e:
        return ActionResult(False, tr("Failed: {error}").format(error=e))
    return ActionResult(True, tr("“{old}” is now called “{new}”.").format(old=p.name, new=new))


def _move_file(args: dict) -> ActionResult:
    """Moves a file or folder into another folder."""
    name = (args.get("name") or "").strip()
    folder = (args.get("folder") or "").strip()
    if not name or not folder:
        return ActionResult(False, tr("I need the file and the destination folder."))
    p = _safe_path(name)
    low = folder.lower()
    if low in FOLDER_KEYS:
        d = Path(_xdg_dir(FOLDER_KEYS[low]))
    elif low in ("", "home", "personale", "casa", "home folder"):  # i18n-data
        d = _home()
    else:
        d = _safe_path(folder)
    if p is None or not p.exists():
        return ActionResult(False, tr("Can't find “{name}”.").format(name=name))
    if d is None or not d.is_dir():
        return ActionResult(False, tr("“{name}” isn't a folder.").format(name=folder))
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
    """Closes a program by name, gracefully: the same close as the agent
    (windows closed with the normal request, a check that they are gone,
    never KILL). This used to be «pkill -f <name>», which closed any process
    with that word in its command line and said «closed» without checking."""
    from .agent import capabilities
    es = capabilities.close_application({"app": (args.get("app") or "").strip()})
    return ActionResult(bool(es.ok), es.message)


def _screenshot(args: dict) -> ActionResult:
    """Saves a screenshot in the Pictures folder."""
    if not shutil.which("grim"):
        return ActionResult(False, tr("The screenshot tool isn't available."))
    # the Pictures folder has a different name in every language (Immagini...):
    # ask xdg-user-dir, as for the other folders
    folder = Path(_xdg_dir("PICTURES"))
    if folder == _home():
        folder = _home() / "Immagini"  # i18n-data: historical fallback name
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / (tr("screenshot-{time}.png").format(time=time.strftime("%Y%m%d-%H%M%S")))
    # With a time limit: if the compositor does not answer the screen copy
    # request, a message after twelve seconds is better than a window stuck
    # forever.
    try:
        r = subprocess.run(["grim", str(dest)], capture_output=True, text=True, timeout=12)
    except subprocess.TimeoutExpired:
        return ActionResult(False, tr("The screenshot wasn't taken in time: "
                                      "the compositor didn't respond."))
    if r.returncode != 0 or not dest.exists():
        return ActionResult(False, (r.stderr or "").strip() or tr("Screenshot failed."))
    return ActionResult(True, tr("Screenshot saved in {folder}: {name}").format(
        folder=folder.name, name=dest.name))


def _search_content(args: dict) -> ActionResult:
    """Searches for a word INSIDE files, not just in their names.

    It uses the zeta-search index, which also reads the text of PDFs and the
    text recognized in images: it is the only way to find «la fattura di
    marzo» when the file is called «scan_0012.pdf».
    """
    text = (args.get("text") or "").strip()
    if not text:
        return ActionResult(False, tr("What should I search for?"))
    if not shutil.which("zeta-index"):
        return ActionResult(False, tr("Content search isn't available."))
    try:
        r = subprocess.run(["zeta-index", "--search", text], capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return ActionResult(False, tr("Search failed: {error}").format(error=e))
    lines = [x for x in (r.stdout or "").splitlines() if x.strip()][:15]
    if not lines:
        return ActionResult(True, tr("No file contains “{text}”.").format(text=text))
    return ActionResult(True, ntr("Found in {n} file:", "Found in {n} files:", len(lines)).format(
        n=len(lines)) + "\n" + "\n".join(lines))


def _package(operation: str, args: dict) -> ActionResult:
    name = (args.get("name") or "").strip()
    if not name or not all(c.isalnum() or c in ".+-" for c in name):
        return ActionResult(False, tr("Invalid program name."))
    if not shutil.which("pkexec"):
        return ActionResult(False, tr("I can't ask for administrator permissions."))
    done = tr("Installed {name}.") if operation == "install" else tr("Removed {name}.")
    return _simple(["pkexec", "apt-get", "-y", operation, name], done.format(name=name))


def _propose_command(args: dict) -> ActionResult:
    """Prepares a command for the user: in the clipboard, with the terminal open.

    It runs nothing. It is a way of saying «I know what is needed, here it
    is» while leaving the decision to whoever sits at the screen.
    """
    command = (args.get("command") or "").strip()
    if not command:
        return ActionResult(False, tr("No command to suggest."))
    reason = (args.get("why") or "").strip()
    copied = False
    for tool in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(tool[0]):
            try:
                subprocess.run(tool, input=command, text=True, timeout=5)
                copied = True
                break
            except (OSError, subprocess.SubprocessError):
                pass
    terminal = shutil.which("foot")
    if terminal:
        try:
            _popen([terminal], start_new_session=True)
        except OSError:
            pass
    text = tr("You need this command:") + "\n\n    %s\n" % command
    if reason:
        text += "\n(%s)\n" % reason
    text += "\n" + (tr("I copied it to the clipboard and opened the terminal: paste it "
                        "with Ctrl+Shift+V and press Enter.") if copied
                     else tr("I opened the terminal: type it there and press Enter."))
    return ActionResult(True, text)


def _open_file(args: dict) -> ActionResult:
    """Opens a file with the system's default program.

    The path stays confined to the home folder, as for folders: ZETA must
    not be able to open system files on command.
    """
    name = (args.get("name") or "").strip()
    if not name:
        return ActionResult(False, tr("Which file?"))
    p = _safe_path(name)
    if p is None or not p.is_file():
        # not a path: search by name in the home folder
        found = _run(["sh", "-c",
                        "find %s -maxdepth 6 -iname %s -type f 2>/dev/null | head -n 5"
                        % (shlex.quote(str(_home())), shlex.quote("*%s*" % name))])
        lines = [r for r in found.splitlines() if r.strip()]
        if not lines:
            return ActionResult(False, tr("Can't find any file called “{name}”.").format(name=name))
        if len(lines) > 1:
            listing = "\n".join("  " + os.path.relpath(r, str(_home())) for r in lines)
            return ActionResult(False, tr("There's more than one, tell me which:") + "\n" + listing)
        p = Path(lines[0])
    open_at = shutil.which("gio") or shutil.which("xdg-open")
    if not open_at:
        return ActionResult(False, tr("No app available to open files."))
    cmd = [open_at, "open", str(p)] if os.path.basename(open_at) == "gio" else [open_at, str(p)]
    try:
        _popen(cmd, start_new_session=True)
        return ActionResult(True, tr("Opening {name}.").format(name=p.name))
    except OSError as e:
        return ActionResult(False, tr("Couldn't open it: {error}").format(error=e))


def _open_url(args: dict) -> ActionResult:
    """Opens an address in the browser.

    Only http and https: other schemes (file://, commands, local paths) do
    not go through here, otherwise ZETA would become a way to make the
    system open anything.
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
    """Changes the wallpaper, or goes back to the one generated by ZETA RAYS."""
    name = (args.get("name") or "").strip()
    if not shutil.which("zeta-wallpaper"):
        return ActionResult(False, tr("The wallpaper command isn't available."))
    if not name or name.lower() in ("predefinito", "default", "zeta", "zeta rays", "originale", "original"):  # i18n-data
        r = _run(["zeta-wallpaper", "reset"])
        return ActionResult(True, tr("Restored the ZETA RAYS wallpaper.") + (" " + r if r else ""))
    from system import wallpapers
    official = wallpapers.search(name)
    if official:
        _run(["zeta-wallpaper", "set", official])
        # report «done» only if zeta-wallpaper really confirms the choice
        if _run(["zeta-wallpaper", "get"]).split("\n")[0].strip() != official:
            return ActionResult(False, tr("I couldn't change the wallpaper."))
        return ActionResult(True, tr("Wallpaper changed: {name}.").format(name=wallpapers.name_of(official)))
    p = _safe_path(name)
    if p is None or not p.is_file():
        return ActionResult(False, tr("Can't find the image “{name}”.").format(name=name))
    r = _run(["zeta-wallpaper", "set", str(p)])
    return ActionResult(True, tr("Wallpaper changed to {name}.").format(name=p.name) + (" " + r if r else ""))


SETTINGS_PAGES = {"appearance", "network", "bluetooth", "audio", "ai", "security", "packages", "info"}
# words the user (or the model) may use for a page -> page key  # i18n-data-begin
SETTINGS_ALIASES = {"wifi": "network", "wi-fi": "network", "rete": "network", "suono": "audio",
                    "intelligenza": "ai", "assistente": "ai", "tema": "appearance", "colore": "appearance",
                    "aspetto": "appearance", "sicurezza": "security", "pacchetti": "packages",
                    "informazioni": "info", "sistema": "info",
                    "theme": "appearance", "color": "appearance", "wallpaper": "appearance",
                    "sound": "audio", "assistant": "ai",
                    "about": "info", "system": "info"}
# i18n-data-end


def page_name(page: str) -> str:
    """Display name of a Settings page."""
    names = {"appearance": tr("Appearance"), "network": tr("Network"), "bluetooth": "Bluetooth",
            "audio": tr("Sound"), "ai": "AI", "security": tr("Security"),
            "packages": tr("Packages"), "info": tr("About")}
    return names.get(page, page)


def _open_settings(args: dict) -> ActionResult:
    exe = shutil.which("zeta-settings")
    if not exe:
        return ActionResult(False, tr("Settings isn't available."))
    page = (args.get("page") or "").strip().lower()
    page = SETTINGS_ALIASES.get(page, page)
    cmd = [exe] + ([page] if page in SETTINGS_PAGES else [])
    try:
        _popen(cmd, start_new_session=True)
        if page in SETTINGS_PAGES:
            return ActionResult(True, tr("Opening Settings › {page}.").format(page=page_name(page)))
        return ActionResult(True, tr("Opening Settings."))
    except OSError as e:
        return ActionResult(False, tr("Couldn't open Settings: {error}").format(error=e))


_WEEKDAYS = (tr("Monday"), tr("Tuesday"), tr("Wednesday"), tr("Thursday"), tr("Friday"),
           tr("Saturday"), tr("Sunday"))
_MONTHS = (tr("January"), tr("February"), tr("March"), tr("April"), tr("May"), tr("June"),
         tr("July"), tr("August"), tr("September"), tr("October"), tr("November"), tr("December"))


def _current_time() -> ActionResult:
    import datetime
    now = datetime.datetime.now()
    return ActionResult(True, tr("It's {time}.").format(time=now.strftime("%H:%M")))


def _current_date() -> ActionResult:
    import datetime
    o = datetime.date.today()
    return ActionResult(True, tr("Today is {weekday}, {month} {day}, {year}.").format(
        weekday=_WEEKDAYS[o.weekday()], day=o.day, month=_MONTHS[o.month - 1], year=o.year))


def _battery_status() -> ActionResult:
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import power
    b = power.battery()
    if not b:
        return ActionResult(True, tr("This computer doesn't have a battery."))
    state = b.get("state") or ""
    if state:
        return ActionResult(True, tr("Battery at {percent}% — {state}.").format(
            percent=b.get("percent", "?"), state=state))
    return ActionResult(True, tr("Battery at {percent}%.").format(percent=b.get("percent", "?")))


def _volume_status() -> ActionResult:
    out = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=4, env=_ENV_C)
    if not out or "Volume" not in out:
        return ActionResult(False, tr("I can't read the volume."))
    muted = "MUTED" in out
    try:
        value = float(out.split()[1])
    except (IndexError, ValueError):
        return ActionResult(False, tr("I can't read the volume."))
    text = tr("Volume at {level}% (muted).") if muted else tr("Volume at {level}%.")
    return ActionResult(True, text.format(level=round(value * 100)))


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
    open_windows = w.open_windows()
    minimized = w.minimized()
    none_label = "  " + tr("(none)")
    lines = [tr("Open windows:")]
    lines += ["  • " + tr("{title} (workspace {n})").format(title=x["title"][:50], n=x["workspace"])
              for x in open_windows] or [none_label]
    lines.append(tr("Minimized:"))
    lines += ["  • %s" % x["title"][:50] for x in minimized] or [none_label]
    return ActionResult(True, "\n".join(lines))


def _set_theme(args: dict) -> ActionResult:
    theme = (args.get("theme") or "").strip().lower()
    # the model may answer in Italian too  # i18n-data
    theme = ("light" if theme.startswith(("light", "chiar")) else  # i18n-data
             "dark" if theme.startswith(("dark", "scur")) else "")  # i18n-data
    if theme not in ("light", "dark"):
        return ActionResult(False, tr("Invalid theme: use “light” or “dark”."))
    p = subprocess.run(["zeta-appearance", "set", "theme", theme],
                       capture_output=True, text=True)
    if p.returncode == 0:
        return ActionResult(True, tr("Light theme applied.") if theme == "light"
                            else tr("Dark theme applied."))
    return ActionResult(False, tr("I couldn't change the theme."))


def _close_active_window() -> ActionResult:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ActionResult(False, tr("No desktop session is running."))
    # ZETA RAYS's Hyprland uses Lua dispatchers: the classic form does not work.
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
    """The menu apps (single registry: Flatpak and AppImage too)."""
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import applications
    names = [a.name for a in applications.menu()]
    return tr("Available apps:") + "\n" + ", ".join(names[:60]) if names else tr("No apps found.")


def _set_accent(args: dict) -> ActionResult:
    color = args.get("color", "")
    exe = shutil.which("zeta-accent")
    if not exe:
        return ActionResult(False, tr("The {command} command isn't available.").format(command="zeta-accent"))
    p = subprocess.run([exe, color], capture_output=True, text=True)
    if p.returncode == 0:
        return ActionResult(True, tr("Accent color set to {color}.").format(color=color))
    return ActionResult(False, (p.stderr or tr("Invalid color.")).strip())
