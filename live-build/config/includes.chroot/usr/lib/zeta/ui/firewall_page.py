# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings › Firewall & SSH.

The firewall (nftables, /etc/nftables.conf: everything that is not listed is
refused) and the SSH server, through the same commands the rest of the
system uses: zeta-ssh for SSH (port 22: off, local network only, or from the
internet too) and systemctl for the firewall service. Nothing here writes
firewall rules by hand.

Turning the firewall off asks for confirmation and says what it exposes.
SSH stays on port 22; root can never log in with SSH (sshd_config.d/zeta.conf).
"""
import subprocess

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from ui.page_tools import bg, confirm, spawn, toast  # noqa: E402


def _out(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def state():
    cfg = {}
    for line in _out(["zeta-ssh", "config"]).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"')
    return {"firewall": _out(["systemctl", "is-active", "nftables.service"]).strip() == "active",
            "ssh_enabled": cfg.get("SSH_ENABLED") == "true",
            "ssh_remote": cfg.get("SSH_REMOTE_ACCESS") == "true",
            "ssh_port": cfg.get("SSH_PORT", "22"),
            "ssh_status": _out(["zeta-ssh", "status"]).strip()}


class FirewallPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self._busy = False
        self.st = {}

        g = Adw.PreferencesGroup(
            title=tr("Firewall"),
            description=tr("Refuses every connection from outside that you did not allow. Programs on this "
                           "computer can still reach the internet."))
        self.fw = Adw.SwitchRow(title=tr("Firewall"), subtitle="…")
        self.fw.connect("notify::active", self._on_firewall)
        g.add(self.fw)
        for title, sub in ((tr("Always allowed"), tr("Replies to your own connections, network setup (DHCP), ping")),
                           (tr("Local network only"), tr("Printers and devices (mDNS), Windows PCs and NAS discovery, ZETA Share")),
                           (tr("Turned on by you"), tr("SSH, below"))):
            g.add(Adw.ActionRow(title=title, subtitle=sub))
        self.add(g)

        g = Adw.PreferencesGroup(
            title=tr("Remote access (SSH)"),
            description=tr("Log in to this computer from another one with ssh. Port 22. Root can never log in "
                           "with SSH; addresses that keep failing the password are blocked by ZETA WATCH."))
        self.ssh = Adw.SwitchRow(title=tr("SSH server"), subtitle="…")
        self.ssh.connect("notify::active", self._on_ssh)
        g.add(self.ssh)
        self.remote = Adw.SwitchRow(
            title=tr("Also from the internet"),
            subtitle=tr("Off: only from your local network. On: needs port 22 forwarded on the router"))
        self.remote.connect("notify::active", self._on_remote)
        g.add(self.remote)
        self.status_row = Adw.ActionRow(title=tr("Status"), subtitle="…")
        self.status_row.set_subtitle_selectable(True)
        g.add(self.status_row)
        diag = Adw.ActionRow(title=tr("Check the connection"),
                             subtitle=tr("Checks every step, network card to SSH server, and says what is wrong"))
        b = Gtk.Button(label=tr("Check"), valign=Gtk.Align.CENTER)
        b.connect("clicked", self._on_diagnose)
        diag.add_suffix(b)
        g.add(diag)
        self.add(g)
        self.refresh()

    def refresh(self):
        bg(state, self._show)

    def _show(self, st):
        self.st = st
        self._busy = True
        self.fw.set_active(st["firewall"])
        self.fw.set_subtitle(tr("On: everything not listed below is refused") if st["firewall"]
                             else tr("Off: this computer accepts connections to every open port"))
        self.ssh.set_active(st["ssh_enabled"])
        self.ssh.set_subtitle(tr("On, port {port}").format(port=st["ssh_port"]) if st["ssh_enabled"] else tr("Off"))
        self.remote.set_active(st["ssh_remote"])
        self.remote.set_sensitive(st["ssh_enabled"])
        lines = [l for l in st["ssh_status"].splitlines() if l.strip()][:6]
        self.status_row.set_subtitle("\n".join(lines) or "…")
        self._busy = False

    def _run(self, cmd, done_text):
        def done(ok):
            toast(self, done_text if ok else tr("Not changed (password not given?)"))
            self.refresh()
        bg(lambda: subprocess.run(cmd, capture_output=True, timeout=180).returncode == 0, done)

    def _on_firewall(self, row, _p):
        if self._busy:
            return
        if row.get_active():
            self._run(["pkexec", "systemctl", "enable", "--now", "nftables.service"], tr("Firewall on"))
            return
        self._busy = True
        row.set_active(True)
        self._busy = False
        confirm(self, tr("Turn the firewall off?"),
                tr("Every program that waits for connections becomes reachable from the network, including from "
                   "the internet if the router lets it through. ZETA WATCH can no longer block addresses."),
                tr("Turn off"),
                lambda: self._run(["pkexec", "systemctl", "disable", "--now", "nftables.service"], tr("Firewall off")),
                destructive=True)

    def _on_ssh(self, row, _p):
        if self._busy:
            return
        on = row.get_active()
        self._run(["pkexec", "zeta-ssh", "on" if on else "off"], tr("Remote access on") if on else tr("Remote access off"))

    def _on_remote(self, row, _p):
        if self._busy:
            return
        on = row.get_active()
        self._run(["pkexec", "zeta-ssh", "remote", "on" if on else "off"],
                  tr("SSH open from the internet") if on else tr("SSH limited to the local network"))

    def _on_diagnose(self, *_a):
        script = 'pkexec zeta-ssh diagnose; printf "\\n%s" "$1"; read _'
        if not spawn("foot", "-e", "sh", "-c", script, "_", tr("Press Enter to close.")):
            toast(self, tr("The terminal could not be opened"))
