# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings › ZETA WATCH: the security monitoring.

What is watched (system settings, /etc/zeta/watch.json, changed through
`pkexec /usr/libexec/zeta-watch config set KEY VALUE`), how alerts reach
this user (~/.config/zeta/watch-notify.json, read by zeta-watch-notify),
the addresses blocked now, the security check, and the history of events
(/var/log/zeta-watch/events.jsonl, readable by administrators).

Turning a protection off asks for confirmation and says what is lost.
"""
import json
import os
import subprocess

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

from i18n import tr  # noqa: E402
from security import watch_text  # noqa: E402
from ui.page_tools import bg, confirm, run_quiet, spawn, toast  # noqa: E402

WATCH = "/usr/libexec/zeta-watch"
EVENTS = "/var/log/zeta-watch/events.jsonl"
NOTIFY = os.path.expanduser("~/.config/zeta/watch-notify.json")
HISTORY = 150


def system_status():
    try:
        out = subprocess.run([WATCH, "status"], capture_output=True, text=True, timeout=20).stdout
        return json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def notify_prefs():
    p = {"desktop": True, "spoken": False, "level": "warning"}
    try:
        with open(NOTIFY, encoding="utf-8") as f:
            saved = json.load(f)
        p.update({k: v for k, v in saved.items() if k in p and type(v) is type(p[k])})
    except (OSError, ValueError, AttributeError):
        pass
    return p


def save_notify(p):
    os.makedirs(os.path.dirname(NOTIFY), exist_ok=True)
    with open(NOTIFY + ".tmp", "w", encoding="utf-8") as f:
        json.dump(p, f)
    os.replace(NOTIFY + ".tmp", NOTIFY)


def history():
    try:
        with open(EVENTS, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-HISTORY:]
    except OSError:
        return None
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# (key, title, subtitle, what is lost when turned off)
PROTECTIONS = [
    ("ssh", tr("SSH logins"), tr("Failed and successful remote logins"),
     tr("Password guessing over SSH will no longer be reported or blocked.")),
    ("logins", tr("Logins and passwords"), tr("Wrong passwords at login, lock screen and administrator prompts"),
     tr("Wrong passwords typed on this computer will no longer be reported.")),
    ("root", tr("Root and administrator rights"), tr("Root sessions, refused administrator commands"),
     tr("Logins as root will no longer be reported.")),
    ("accounts", tr("User accounts"), tr("New users, administrator rights given, passwords changed"),
     tr("A new account or new administrator rights will no longer be reported.")),
    ("files", tr("Important files"), tr("Accounts, administrator rights, SSH and autostart files (auditd)"),
     tr("Changes to the files that decide who can log in will no longer be reported.")),
    ("network", tr("Network"), tr("New open ports and unusual outgoing connections"),
     tr("A program that starts accepting connections will no longer be reported.")),
    ("processes", tr("Programs"), tr("Programs running from temporary folders or deleted files"),
     tr("A common sign of malware will no longer be checked.")),
    ("services", tr("Services"), tr("New services that start by themselves"), ""),
    ("firewall", tr("Firewall"), tr("Changes to the firewall rules"), ""),
    ("scans", tr("Weekly malware and rootkit check"), tr("rkhunter and chkrootkit, at idle priority"),
     tr("Known rootkits and changed system programs will no longer be looked for.")),
]


class WatchPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.status = {}
        self.notify = notify_prefs()
        self._busy = False

        # --- status
        self.state_group = Adw.PreferencesGroup(
            title="ZETA WATCH",
            description=tr("Watches the system for suspicious activity and tells you at once. It reports "
                           "what the system records; it cannot promise to catch every attack or every "
                           "malware."))
        self.state_row = Adw.ActionRow(title=tr("Checking…"))
        self.state_group.add(self.state_row)
        test = Adw.ActionRow(title=tr("Send a test alert"), subtitle=tr("To see how an alert looks and sounds"))
        b = Gtk.Button(label=tr("Test"), valign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: self._admin(["test"], tr("Test alert sent")))
        test.add_suffix(b)
        self.state_group.add(test)
        self.add(self.state_group)

        # --- what is watched
        self.watch_group = Adw.PreferencesGroup(title=tr("What is watched"))
        self.switches = {}
        for key, title, sub, lost in PROTECTIONS:
            row = Adw.SwitchRow(title=title, subtitle=sub, sensitive=False)
            row.connect("notify::active", self._on_protection, key, lost)
            self.watch_group.add(row)
            self.switches[key] = row
        self.add(self.watch_group)

        # --- blocking
        self.block_group = Adw.PreferencesGroup(
            title=tr("Blocking"),
            description=tr("An address that keeps failing SSH passwords is blocked for a while. Connections "
                           "already open are never cut, and this computer is never blocked."))
        self.block = Adw.SwitchRow(title=tr("Block addresses that keep failing"), sensitive=False)
        self.block.connect("notify::active", self._on_protection, "block",
                           tr("Addresses that keep guessing passwords will no longer be blocked."))
        self.block_group.add(self.block)
        self.block_lan = Adw.SwitchRow(
            title=tr("Also on the local network"),
            subtitle=tr("Off: computers of your own network are never blocked (you cannot lock yourself out)"),
            sensitive=False)
        self.block_lan.connect("notify::active", self._on_protection, "block_lan", "")
        self.block_group.add(self.block_lan)
        self.blocked_row = Adw.ActionRow(title=tr("Blocked now"), subtitle="…")
        b = Gtk.Button(label=tr("Unblock all"), valign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: self._admin(["unblock", "all"], tr("Every address unblocked")))
        self.blocked_row.add_suffix(b)
        self.block_group.add(self.blocked_row)
        self.add(self.block_group)

        # --- alerts for me
        g = Adw.PreferencesGroup(title=tr("Alerts"))
        row = Adw.SwitchRow(title=tr("Desktop notifications"), active=self.notify["desktop"])
        row.connect("notify::active", lambda r, _p: self._set_notify("desktop", r.get_active()))
        g.add(row)
        row = Adw.SwitchRow(title=tr("Read alerts aloud"),
                            subtitle=tr("Warnings and critical alerts, with the voice chosen in Settings › AI"),
                            active=self.notify["spoken"])
        row.connect("notify::active", lambda r, _p: self._set_notify("spoken", r.get_active()))
        g.add(row)
        levels = ["notice", "warning", "critical"]
        row = Adw.ComboRow(title=tr("Show alerts from"),
                           subtitle=tr("Lower levels are kept in the history below"),
                           model=Gtk.StringList.new([tr("Notices and above"), tr("Warnings and above"),
                                                     tr("Critical only")]))
        row.set_selected(levels.index(self.notify["level"]) if self.notify["level"] in levels else 1)
        row.connect("notify::selected", lambda r, _p: self._set_notify("level", levels[r.get_selected()]))
        g.add(row)
        self.add(g)

        # --- network intrusion detection (optional)
        self.ids_group = Adw.PreferencesGroup(
            title=tr("Network intrusion detection (Suricata)"),
            description=tr("Compares network traffic with thousands of known attack patterns. It uses "
                           "about 400-700 MB of memory and some processor all the time: recommended only "
                           "with 16 GB of memory or more. It is installed the first time you turn it on."))
        self.ids = Adw.SwitchRow(title=tr("Suricata"), sensitive=False)
        self.ids.connect("notify::active", self._on_suricata)
        self.ids_group.add(self.ids)
        self.add(self.ids_group)

        # --- history
        self.hist_group = Adw.PreferencesGroup(title=tr("History"))
        self.add(self.hist_group)
        self._hist_rows = []

        self.refresh()

    # ------------------------------------------------------------ state
    def refresh(self):
        bg(system_status, self._show_status)
        bg(history, self._show_history)

    def _show_status(self, st):
        self.status = st or {}
        cfg = self.status.get("config", {})
        self._busy = True
        if not self.status:
            self.state_row.set_title(tr("ZETA WATCH is not available"))
            self.state_row.set_subtitle(tr("The service is missing on this system."))
        elif self.status.get("service"):
            self.state_row.set_title(tr("Monitoring is on"))
            self.state_row.set_subtitle(tr("Important-file monitoring (auditd): {state}").format(
                state=tr("active") if self.status.get("auditd") else tr("not running")))
        else:
            self.state_row.set_title(tr("Monitoring is off"))
            self.state_row.set_subtitle(tr("The service is not running (it does not run in the live session)."))
        for key, row in self.switches.items():
            row.set_active(bool(cfg.get(key, True)))
            row.set_sensitive(bool(self.status))
        self.block.set_active(bool(cfg.get("block", True)))
        self.block_lan.set_active(bool(cfg.get("block_lan", False)))
        for r in (self.block, self.block_lan, self.ids):
            r.set_sensitive(bool(self.status))
        blocked = self.status.get("blocked", [])
        self.blocked_row.set_subtitle(", ".join(blocked) if blocked else tr("No address"))
        self.ids.set_active(bool(cfg.get("suricata")) and bool(self.status.get("suricata_installed")))
        self.ids.set_subtitle(tr("Running") if self.status.get("suricata_running") else
                              (tr("Installed, off") if self.status.get("suricata_installed") else tr("Not installed")))
        self._busy = False

    def _show_history(self, events):
        for r in self._hist_rows:
            self.hist_group.remove(r)
        self._hist_rows = []
        if events is None:
            row = Adw.ActionRow(title=tr("Only administrators can read the history."))
            self.hist_group.add(row)
            self._hist_rows.append(row)
            return
        if not events:
            row = Adw.ActionRow(title=tr("Nothing to report yet."))
            self.hist_group.add(row)
            self._hist_rows.append(row)
            return
        for e in events:
            title, text, advice = watch_text.describe(e)
            when = (e.get("time") or "")[:16].replace("T", " ")
            row = Adw.ExpanderRow(title=GLib.markup_escape_text(title),
                                  subtitle=GLib.markup_escape_text("%s · %s" % (
                                      when, watch_text.severity_name(e.get("severity", "")))))
            row.add_css_class("watch-" + e.get("severity", "info"))
            for line in [text, advice] + list((e.get("params") or {}).get("lines", []))[:10]:
                if line:
                    lab = Gtk.Label(label=line, wrap=True, xalign=0, selectable=True,
                                    wrap_mode=Pango.WrapMode.WORD_CHAR,
                                    margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
                    row.add_row(lab)
            self.hist_group.add(row)
            self._hist_rows.append(row)

    # ------------------------------------------------------------ actions
    def _admin(self, args, done_text):
        def done(res):
            if res is True:
                toast(self, done_text)
            else:
                toast(self, tr("Not changed (password not given?)"))
            self.refresh()
        bg(lambda: run_quiet(["pkexec", WATCH] + args, timeout=120), done)

    def _on_protection(self, row, _p, key, lost):
        if self._busy:
            return
        on = row.get_active()
        if on or not lost:
            self._admin(["config", "set", key, "true" if on else "false"], tr("Saved"))
            return
        # turning a protection off: say what is lost, and ask
        self._busy = True
        row.set_active(True)
        self._busy = False

        def really():
            self._busy = True
            row.set_active(False)
            self._busy = False
            self._admin(["config", "set", key, "false"], tr("Saved"))
        confirm(self, tr("Turn this protection off?"), lost, tr("Turn off"), really, destructive=True)

    def _on_suricata(self, row, _p):
        if self._busy:
            return
        on = row.get_active()
        if on and not self.status.get("suricata_installed"):
            # installed in a visible terminal: it downloads packages and rules
            script = ('printf "\\033[1;34m%s\\033[0m\\n\\n" "$1"; pkexec /usr/libexec/zeta-watch-suricata install; '
                      'printf "\\n%s" "$2"; read _')
            if spawn("foot", "-e", "sh", "-c", script, "_", tr("ZETA WATCH: installing Suricata"),
                     tr("Press Enter to close.")):
                toast(self, tr("Installing Suricata in a terminal window…"))
            else:
                toast(self, tr("The terminal could not be opened"))
            return
        self._admin(["config", "set", "suricata", "true" if on else "false"], tr("Saved"))

    def _set_notify(self, key, value):
        self.notify[key] = value
        try:
            save_notify(self.notify)
        except OSError as e:
            toast(self, tr("Not saved: {error}").format(error=e))
