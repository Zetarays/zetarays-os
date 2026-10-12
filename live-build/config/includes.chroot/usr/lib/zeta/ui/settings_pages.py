# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Settings — Network, Bluetooth, Printers and Audio pages (libadwaita).

They replace the generic windows (nm-connection-editor, blueman, pavucontrol)
with the same look as the rest of ZETA RAYS. Slow commands run in threads; the
UI is updated through GLib.idle_add and never blocks.
"""
import os
import re
import subprocess
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from i18n import tr, trc  # noqa: E402
from system import audio, bluetooth, network, run, printers  # noqa: E402


def bg(work, done=None):
    """Run work() in a thread, then done(result) in the UI thread."""
    def runner():
        res = work()
        if done:
            GLib.idle_add(lambda: (done(res), False)[1])
    threading.Thread(target=runner, daemon=True).start()


def clear_group(group, rows):
    for r in rows:
        group.remove(r)
    rows.clear()


def status_row(title, subtitle=""):
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    r.set_subtitle_selectable(True)
    return r


def toast(widget, text):
    w = widget.get_root()
    if hasattr(w, "toast"):
        w.toast(text)


# =============================== NETWORK ===============================
class NetworkPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.wifi_rows, self.vpn_rows = [], []

        # Status
        self.g_state = Adw.PreferencesGroup(title=tr("Status"))
        self.r_conn = status_row(tr("Connection"), "…")
        self.r_ip = status_row(tr("IP address"), "…")
        self.r_gw = status_row("Gateway", "…")
        self.r_dns = status_row("DNS", "…")
        for r in (self.r_conn, self.r_ip, self.r_gw, self.r_dns):
            self.g_state.add(r)
        self.add(self.g_state)

        # Wi-Fi right after the status: it is what people use most; manual
        # IP addresses are for a few and go further down
        self.g_wifi = Adw.PreferencesGroup(title="Wi-Fi")
        self.sw_wifi = Adw.SwitchRow(title="Wi-Fi")
        self.sw_wifi.connect("notify::active", self.on_wifi_switch)
        self.g_wifi.add(self.sw_wifi)
        # a network that does not broadcast its name is not listed: it is typed by hand
        is_hidden = Adw.ActionRow(title=tr("Hidden network"),
                                 subtitle=tr("Not shown in the list: enter its name and password"))
        bn = Gtk.Button(label=tr("Connect…"), valign=Gtk.Align.CENTER)
        bn.connect("clicked", lambda *_: self._ask_hidden())
        is_hidden.add_suffix(bn)
        self.g_wifi.add(is_hidden)
        rescan = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                            tooltip_text=tr("Search for networks"), css_classes=["flat"])
        rescan.connect("clicked", lambda *_: self.load_wifi(rescan=True))
        self.g_wifi.set_header_suffix(rescan)
        self.add(self.g_wifi)

        # IPv4 configuration of the active connection
        self.g_ip = Adw.PreferencesGroup(title=tr("IPv4 address"),
                                         description=tr("Automatic (DHCP) is right almost always."))
        self.ip_mode = Adw.ComboRow(title=tr("Configuration"),
                                    model=Gtk.StringList.new([tr("Automatic (DHCP)"), tr("Manual")]))
        self.ip_addr = Adw.EntryRow(title=tr("Address / prefix (e.g. 192.168.1.20/24)"))
        self.ip_gw = Adw.EntryRow(title="Gateway")
        self.ip_dns = Adw.EntryRow(title=tr("DNS (separated by spaces)"))
        apply = Gtk.Button(label=tr("Apply"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        apply.connect("clicked", lambda *_: self.apply_ip())
        self.ip_mode.connect("notify::selected", lambda *_: self._ip_sensitive())
        for r in (self.ip_mode, self.ip_addr, self.ip_gw, self.ip_dns):
            self.g_ip.add(r)
        self.g_ip.set_header_suffix(apply)
        self.add(self.g_ip)

        # Wi-Fi
        # IPv6: many networks (and every modern mobile carrier) use it, and
        # without these controls the only way to change it was the command
        # line. "Off" is for people whose network gets confused by IPv6: it is
        # the classic fix, and it was missing before.
        self.g_ip6 = Adw.PreferencesGroup(
            title=tr("IPv6 address"),
            description=tr("Automatic is right almost always. Turn it off only if the network has problems."))
        self.ip6_mode = Adw.ComboRow(
            title=tr("Configuration"),
            model=Gtk.StringList.new([tr("Auto"), tr("Manual"), tr("Off")]))
        self.ip6_addr = Adw.EntryRow(title=tr("Address / prefix (e.g. 2001:db8::5/64)"))
        self.ip6_gw = Adw.EntryRow(title="Gateway")
        self.ip6_dns = Adw.EntryRow(title=tr("DNS (separated by spaces)"))
        for r in (self.ip6_mode, self.ip6_addr, self.ip6_gw, self.ip6_dns):
            self.g_ip6.add(r)
        self.ip6_mode.connect("notify::selected", lambda *_: self._ip6_sensitive())
        b6 = Gtk.Button(label=tr("Apply"), halign=Gtk.Align.END, margin_top=6,
                        css_classes=["suggested-action"])
        b6.connect("clicked", lambda *_: self.apply_ip6())
        self.g_ip6.add(b6)
        self.add(self.g_ip6)


        # Remote access (SSH): on opens port 22 to the local network only;
        # "Also from the internet" opens it to the outside too (needs port
        # forwarding on the router). Everything goes through zeta-ssh, with the
        # password, and persists across reboots.
        self.g_ssh = Adw.PreferencesGroup(
            title=tr("Remote access (SSH)"),
            description=tr("To sign in to this computer from another one on the same network "
                           "(home, office). From the internet only if you choose so below."))
        self.sw_ssh = Adw.SwitchRow(title=tr("Remote access"), subtitle="…")
        self.sw_ssh.connect("notify::active", self.on_ssh_switch)
        self.g_ssh.add(self.sw_ssh)
        self.sw_ssh_remote = Adw.SwitchRow(
            title=tr("Also from the internet"),
            subtitle=tr("Off: local network only. Port 22 must also be forwarded on the router."))
        self.sw_ssh_remote.set_sensitive(False)
        self.sw_ssh_remote.connect("notify::active", self.on_ssh_remote_switch)
        self.g_ssh.add(self.sw_ssh_remote)
        self.add(self.g_ssh)
        self._read_ssh()

        # VPN
        self.g_vpn = Adw.PreferencesGroup(title="VPN",
                                          description=tr("WireGuard (.conf) and OpenVPN (.ovpn)."))
        imp = Gtk.Button(label=tr("Import…"), valign=Gtk.Align.CENTER)
        imp.connect("clicked", lambda *_: self.import_vpn())
        self.g_vpn.set_header_suffix(imp)
        self.vpn_empty = Adw.ActionRow(title=tr("No VPN configured"),
                                       subtitle=tr("Import the file you received from your VPN provider"))
        self.g_vpn.add(self.vpn_empty)
        self.add(self.g_vpn)

        # Proxy
        self.g_proxy = Adw.PreferencesGroup(title="Proxy",
                                            description=tr("Used by Firefox, apps and the terminal."))
        self.px_mode = Adw.ComboRow(title=tr("Mode"),
                                    model=Gtk.StringList.new([tr("None"), tr("Manual"), tr("Automatic (PAC)")]))
        self.px_host = Adw.EntryRow(title=tr("Server"))
        self.px_port = Adw.EntryRow(title=tr("Port"))
        self.px_url = Adw.EntryRow(title=tr("PAC file address"))
        papply = Gtk.Button(label=tr("Apply"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        papply.connect("clicked", lambda *_: self.apply_proxy())
        self.px_mode.connect("notify::selected", lambda *_: self._proxy_sensitive())
        for r in (self.px_mode, self.px_host, self.px_port, self.px_url):
            self.g_proxy.add(r)
        self.g_proxy.set_header_suffix(papply)
        self.add(self.g_proxy)

        # Servers and shares: files on other computers (Windows, Mac, NAS,
        # SSH, FTP, WebDAV, NFS), through the "Connect to a server" window
        g_server = Adw.PreferencesGroup(title=tr("Servers and shares"))
        srv = Adw.ActionRow(title=tr("Connect to a server"),
                            subtitle=tr("Folders on Windows PCs, Macs and NAS drives, SSH, FTP, WebDAV and NFS "
                                        "servers, on your home network or on the internet"),
                            activatable=True)
        srv.add_prefix(Gtk.Image(icon_name="zeta-server-network"))
        srv.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        srv.connect("activated", lambda *_: _launch_detached("zeta-server"))
        g_server.add(srv)
        self.add(g_server)

        self.active_conn = None
        self.refresh()
        self.load_proxy()

    # ---- status ----
    def refresh(self):
        def work():
            st = network.status()
            conf = {}
            if st["connected"] and st["name"]:
                out = run(network.NMCLI + ["-t", "-f",
                           "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns,"
                           "ipv6.method,ipv6.addresses,ipv6.gateway,ipv6.dns",
                           "connection", "show", "id", st["name"]]) or ""
                for line in out.splitlines():
                    k, _, v = line.partition(":")
                    conf[k] = v
            gw = run(["ip", "route", "show", "default"]) or ""
            dns = run(network.NMCLI + ["-t", "-f", "IP4.DNS", "device", "show", st["device"]]) if st["device"] else ""
            return st, conf, gw, dns, network.has_wifi(), network.wifi_enabled(), network.vpns()
        bg(work, self._apply_state)

    def _apply_state(self, res):
        st, conf, gw, dns, has_wifi, wifi_on, vpns = res
        kind = {"wifi": "Wi-Fi", "ethernet": "Ethernet"}.get(st["kind"], "")
        self.r_conn.set_subtitle(("%s · %s" % (kind, st["label"])) if st["connected"] else tr("Not connected"))
        self.r_ip.set_subtitle(st["ip"] or "—")
        g = gw.split()
        self.r_gw.set_subtitle(g[2] if len(g) > 2 and g[0] == "default" else "—")
        self.r_dns.set_subtitle(", ".join(l.split(":", 1)[1] for l in (dns or "").splitlines() if ":" in l) or "—")
        self.active_conn = st["name"] if st["connected"] else None
        self.g_ip.set_visible(bool(self.active_conn))
        if conf:
            self.ip_mode.set_selected(1 if conf.get("ipv4.method") == "manual" else 0)
            self.ip_addr.set_text(conf.get("ipv4.addresses", "").split(",")[0])
            self.ip_gw.set_text(conf.get("ipv4.gateway", "").replace("--", ""))
            self.ip_dns.set_text(conf.get("ipv4.dns", "").replace(",", " ").replace("--", ""))
            ipv6_method = conf.get("ipv6.method", "auto")
            self.ip6_mode.set_selected({"manual": 1, "disabled": 2, "ignore": 2}.get(ipv6_method, 0))
            self.ip6_addr.set_text(conf.get("ipv6.addresses", "").split(",")[0].replace("--", ""))
            self.ip6_gw.set_text(conf.get("ipv6.gateway", "").replace("--", ""))
            self.ip6_dns.set_text(conf.get("ipv6.dns", "").replace(",", " ").replace("--", ""))
            self._ip6_sensitive()
            self._ip_sensitive()
        self.g_wifi.set_visible(has_wifi)
        self._setting_wifi = True
        self.sw_wifi.set_active(wifi_on)
        self._setting_wifi = False
        if has_wifi and wifi_on:
            self.load_wifi()
        self.show_vpns(vpns)

    def _ip_sensitive(self):
        manual = self.ip_mode.get_selected() == 1
        for r in (self.ip_addr, self.ip_gw, self.ip_dns):
            r.set_sensitive(manual)

    def _ip6_sensitive(self):
        manual = self.ip6_mode.get_selected() == 1
        for r in (self.ip6_addr, self.ip6_gw, self.ip6_dns):
            r.set_sensitive(manual)

    def apply_ip6(self):
        if not self.active_conn:
            return
        c = self.active_conn
        choice = self.ip6_mode.get_selected()
        if choice == 1:
            addr = self.ip6_addr.get_text().strip()
            if addr and "/" not in addr:
                addr += "/64"
            args = ["ipv6.method", "manual", "ipv6.addresses", addr,
                    "ipv6.gateway", self.ip6_gw.get_text().strip(),
                    "ipv6.dns", self.ip6_dns.get_text().strip().replace(" ", ",")]
        elif choice == 2:
            args = ["ipv6.method", "disabled", "ipv6.addresses", "",
                    "ipv6.gateway", "", "ipv6.dns", ""]
        else:
            args = ["ipv6.method", "auto", "ipv6.addresses", "",
                    "ipv6.gateway", "", "ipv6.dns", ""]

        def work():
            ok = run(["nmcli", "connection", "modify", "id", c] + args,
                     timeout=15, check=True) is not None
            if ok:
                run(["nmcli", "connection", "up", "id", c], timeout=30)
            return ok
        bg(work, lambda ok: (toast(self, tr("IPv6 configuration applied") if ok else
                                   tr("Could not apply: check the values")), self.refresh()))

    def apply_ip(self):
        if not self.active_conn:
            return
        c = self.active_conn
        if self.ip_mode.get_selected() == 1:
            addr = self.ip_addr.get_text().strip()
            if "/" not in addr:
                addr += "/24"
            args = ["ipv4.method", "manual", "ipv4.addresses", addr,
                    "ipv4.gateway", self.ip_gw.get_text().strip(),
                    "ipv4.dns", self.ip_dns.get_text().strip().replace(" ", ",")]
        else:
            args = ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""]

        def work():
            ok = run(["nmcli", "connection", "modify", "id", c] + args, timeout=15, check=True) is not None
            if ok:
                run(["nmcli", "connection", "up", "id", c], timeout=30)
            return ok
        bg(work, lambda ok: (toast(self, tr("Configuration applied") if ok else
                                   tr("Could not apply: check the values")), self.refresh()))

    # ---- Remote access (SSH) ----
    def _read_ssh(self):
        def work():
            try:
                r = subprocess.run(["zeta-ssh", "status"], capture_output=True, text=True, timeout=10)
                c = subprocess.run(["zeta-ssh", "config"], capture_output=True, text=True, timeout=10)
                return r.returncode, r.stdout.strip(), "SSH_REMOTE_ACCESS=true" in c.stdout
            except (OSError, subprocess.SubprocessError) as e:
                return 9, str(e), False
        bg(work, self._show_ssh)

    def _show_ssh(self, res):
        rc, text, remote = res
        enabled = rc == 0
        # the "ssh user@address" commands that zeta-ssh prints for the local
        # network: they are matched by shape (numeric IP address), not by the
        # text around them, which changes with the language. The "from the
        # internet" line has "<public address...>" and is left out.
        commands = re.findall(r"\bssh \S+@[0-9A-Fa-f.:]+(?=\s|$)", text, re.M)
        if enabled:
            below = tr("On. {details}").format(
                details="  ".join(commands) or tr("Port 22 open to the local network."))
        elif rc == 9:
            below = tr("Not available: {error}").format(error=text[:80])
        elif rc == 2:
            below = tr("Half set up: turn it off and on again.")
        else:
            below = tr("Off.")
        self._ssh_updating = True
        self.sw_ssh.set_active(enabled)
        self.sw_ssh_remote.set_active(enabled and remote)
        self._ssh_updating = False
        self.sw_ssh.set_subtitle(below)
        is_live = os.path.exists("/run/live/medium")
        self.sw_ssh_remote.set_sensitive(enabled and not is_live)
        if is_live:
            self.sw_ssh_remote.set_subtitle(
                tr("Not available in the live session (its password “zeta” is known to everyone)."))
        elif enabled and remote:
            self.sw_ssh_remote.set_subtitle(tr("Open from the internet too. Root cannot sign in; too many "
                                               "attempts from the same address are dropped."))
        else:
            self.sw_ssh_remote.set_subtitle(
                tr("Off: local network only. Port 22 must also be forwarded on the router."))

    def on_ssh_remote_switch(self, row, _p):
        if getattr(self, "_ssh_updating", False):
            return
        open_at = row.get_active()
        self.sw_ssh_remote.set_subtitle(tr("Opening…") if open_at else tr("Closing…"))

        def work():
            try:
                r = subprocess.run(["pkexec", "zeta-ssh", "remote", "on" if open_at else "off"],
                                   capture_output=True, text=True, timeout=120)
                return r.returncode, (r.stdout + r.stderr).strip()
            except (OSError, subprocess.SubprocessError) as e:
                return 1, str(e)

        def done(res):
            rc, text = res
            if rc == 0:
                toast(self, tr("SSH open from the internet too") if open_at else tr("SSH from the local network only"))
            elif rc in (126, 127):
                toast(self, tr("Canceled"))
            else:
                toast(self, tr("Failed: {error}").format(
                    error=text.splitlines()[-1] if text else tr("error")))
            self._read_ssh()
        bg(work, done)

    def on_ssh_switch(self, row, _p):
        if getattr(self, "_ssh_updating", False):
            return
        turn_on = row.get_active()
        self.sw_ssh.set_subtitle(tr("Turning on…") if turn_on else tr("Turning off…"))

        def work():
            # pkexec asks for the administrator password (it changes the firewall)
            try:
                r = subprocess.run(["pkexec", "zeta-ssh", "on" if turn_on else "off"],
                                   capture_output=True, text=True, timeout=120)
                return r.returncode, (r.stdout + r.stderr).strip()
            except (OSError, subprocess.SubprocessError) as e:
                return 1, str(e)

        def done(res):
            rc, text = res
            if rc == 0:
                toast(self, tr("Remote access on") if turn_on else tr("Remote access off"))
            elif rc in (126, 127):
                toast(self, tr("Canceled"))
            else:
                toast(self, tr("Failed: {error}").format(
                    error=text.splitlines()[-1] if text else tr("error")))
            self._read_ssh()          # show the real state, not the requested one
        bg(work, done)

    # ---- Wi-Fi ----
    def on_wifi_switch(self, row, _p):
        if getattr(self, "_setting_wifi", False):
            return
        bg(lambda: network.set_wifi(row.get_active()), lambda _r: GLib.timeout_add(1200, self.refresh))

    def load_wifi(self, rescan=False):
        bg(lambda: (network.wifi_networks(rescan), network.known_wifi()), self.show_wifi)

    def show_wifi(self, data):
        nets, saved = data
        clear_group(self.g_wifi, self.wifi_rows)
        if not nets:
            r = Adw.ActionRow(title=tr("No networks found"))
            self.g_wifi.add(r)
            self.wifi_rows.append(r)
        in_progress = getattr(self, "_wifi_in_progress", None)
        for n in nets[:12]:
            lvl = 3 if n["signal"] > 66 else 2 if n["signal"] > 33 else 1
            note = (trc("wifi network", "Connected") if n["active"] else
                    trc("wifi network", "Connecting…") if n["ssid"] == in_progress else
                    trc("wifi network", "Saved") if n["ssid"] in saved else
                    trc("wifi network", "Secured") if n["secure"] else trc("wifi network", "Open"))
            r = Adw.ActionRow(title=n["ssid"], subtitle=note)
            r.add_prefix(Gtk.Image(icon_name="zeta-wifi-%d" % lvl))
            if n["ssid"] in saved and n["secure"]:
                cp = Gtk.Button(icon_name="dialog-password-symbolic", valign=Gtk.Align.CENTER,
                                css_classes=["flat"], tooltip_text=tr("Change password"))
                cp.connect("clicked", lambda _b, n=n: self._ask_password(n["ssid"]))
                r.add_suffix(cp)
            if n["ssid"] in saved:
                dm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                css_classes=["flat"], tooltip_text=tr("Forget network"))
                dm.connect("clicked", lambda _b, n=n: self._forget(n["ssid"]))
                r.add_suffix(dm)
            if not n["active"]:
                b = Gtk.Button(label=tr("Connect"), valign=Gtk.Align.CENTER,
                               sensitive=in_progress is None)
                b.connect("clicked", lambda _b, n=n, s=saved: self.connect_wifi(n, s))
                r.add_suffix(b)
            self.g_wifi.add(r)
            self.wifi_rows.append(r)

    def connect_wifi(self, n, saved=()):
        if n["secure"] and n["ssid"] not in saved:
            self._ask_password(n["ssid"])
        else:
            self._do_connect(n["ssid"], None)

    def _ask_password(self, ssid, error=""):
        """Ask for the password; after a failed attempt ask again with the
        reason shown above, instead of leaving the user without an answer."""
        dlg = Adw.AlertDialog(heading=tr("Password for “{name}”").format(name=ssid), body=error)
        entry = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", tr("Cancel"))
        dlg.add_response("ok", tr("Connect"))
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")
        dlg.set_close_response("cancel")

        def answer(_d, resp):
            pw = entry.get_text()
            if resp != "ok":
                return
            if not pw:
                GLib.idle_add(self._ask_password, ssid, tr("Enter the network password."))
                return
            self._do_connect(ssid, pw)
        dlg.connect("response", answer)
        dlg.present(self.get_root())
        entry.grab_focus()
        return False

    def _ask_hidden(self, error=""):
        dlg = Adw.AlertDialog(heading=tr("Hidden network"), body=error)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        name_entry = Gtk.Entry(placeholder_text=tr("Network name (SSID)"), activates_default=True)
        pw = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True,
                               placeholder_text=tr("Password (empty if the network is open)"))
        box.append(name_entry)
        box.append(pw)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", tr("Cancel"))
        dlg.add_response("ok", tr("Connect"))
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")
        dlg.set_close_response("cancel")

        def answer(_d, resp):
            if resp != "ok":
                return
            ssid = name_entry.get_text().strip()
            if not ssid:
                GLib.idle_add(self._ask_hidden, tr("Enter the network name."))
                return
            self._do_connect(ssid, pw.get_text() or None, is_hidden=True)
        dlg.connect("response", answer)
        dlg.present(self.get_root())
        name_entry.grab_focus()
        return False

    def _do_connect(self, ssid, pw, is_hidden=False):
        if getattr(self, "_wifi_in_progress", None):
            return                                   # one attempt at a time
        self._wifi_in_progress = ssid
        toast(self, tr("Connecting to “{name}”…").format(name=ssid))
        self.load_wifi()

        def done(res):
            ok, msg, reason = res
            self._wifi_in_progress = None
            toast(self, msg)
            self.refresh()
            self._reload_later()
            if reason == "password" and is_hidden:
                self._ask_hidden(msg)
            elif reason == "password":
                self._ask_password(ssid, msg)
        bg(lambda: network.connect_wifi_outcome(ssid, pw, is_hidden=is_hidden), done)

    def _reload_later(self):
        """NetworkManager finishes connecting or disconnecting a moment after
        replying: reload the list again, otherwise it stays "Connected"."""
        GLib.timeout_add(2500, lambda: (self.load_wifi(), False)[1])

    def _forget(self, ssid):
        dlg = Adw.AlertDialog(heading=tr("Forget “{name}”?").format(name=ssid),
                              body=tr("The saved password will be deleted; to reconnect you will "
                                      "have to enter it again."))
        dlg.add_response("cancel", tr("Cancel"))
        dlg.add_response("ok", tr("Forget"))
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, resp: bg(
            lambda: network.forget_wifi(ssid),
            lambda ok: (toast(self, (tr("“{name}” forgotten") if ok else
                                     tr("Could not forget “{name}”")).format(name=ssid)),
                        self.refresh(), self._reload_later())) if resp == "ok" else None)
        dlg.present(self.get_root())

    # ---- VPN ----
    def show_vpns(self, vpns):
        clear_group(self.g_vpn, self.vpn_rows)
        self.vpn_empty.set_visible(not vpns)
        for v in vpns:
            r = Adw.ActionRow(title=v["name"], subtitle=(tr("{type} · active").format(type=v["type"])
                                                         if v["active"] else v["type"]))
            r.add_prefix(Gtk.Image(icon_name="zeta-vpn"))
            sw = Gtk.Switch(active=v["active"], valign=Gtk.Align.CENTER)
            sw.connect("state-set", lambda _s, on, v=v: self.set_vpn(v, on))
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                            css_classes=["flat"], tooltip_text=tr("Remove"))
            rm.connect("clicked", lambda _b, v=v: self.remove_vpn(v))
            r.add_suffix(sw)
            r.add_suffix(rm)
            self.g_vpn.add(r)
            self.vpn_rows.append(r)

    def set_vpn(self, v, on):
        bg(lambda: network.set_vpn(v["uuid"], on),
           lambda ok: (toast(self, ((tr("VPN {name} turned on") if on else tr("VPN {name} turned off"))
                                    .format(name=v["name"]) if ok else
                                    (tr("Could not turn on the VPN") if on else tr("Could not turn off the VPN")))),
                       self.refresh()))
        return False

    def remove_vpn(self, v):
        dlg = Adw.AlertDialog(heading=tr("Remove the VPN “{name}”?").format(name=v["name"]),
                              body=tr("The configuration will be deleted from this computer."))
        dlg.add_response("cancel", tr("Cancel"))
        dlg.add_response("rm", tr("Remove"))
        dlg.set_response_appearance("rm", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response", lambda _d, r: bg(lambda: network.remove_connection(v["uuid"]),
                                                 lambda _ok: self.refresh()) if r == "rm" else None)
        dlg.present(self.get_root())

    def import_vpn(self):
        filt = Gtk.FileFilter(name=tr("VPN configurations"))
        filt.add_pattern("*.conf")
        filt.add_pattern("*.ovpn")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filt)
        dlg = Gtk.FileDialog(title=tr("Import VPN"), filters=filters)

        def chosen(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            bg(lambda: network.import_vpn(f.get_path()),
               lambda r: (toast(self, r[1]), self.refresh()))
        dlg.open(self.get_root(), None, chosen)

    # ---- proxy ----
    def load_proxy(self):
        def done(p):
            self.px_mode.set_selected({"none": 0, "manual": 1, "auto": 2}.get(p["mode"], 0))
            self.px_host.set_text(p["host"])
            self.px_port.set_text(str(p["port"] or ""))
            self.px_url.set_text(p["url"])
            self._proxy_sensitive()
        bg(network.proxy, done)

    def _proxy_sensitive(self):
        m = self.px_mode.get_selected()
        self.px_host.set_visible(m == 1)
        self.px_port.set_visible(m == 1)
        self.px_url.set_visible(m == 2)

    def apply_proxy(self):
        m = ["none", "manual", "auto"][self.px_mode.get_selected()]
        port = self.px_port.get_text().strip()
        bg(lambda: network.set_proxy(m, self.px_host.get_text().strip(),
                                     int(port) if port.isdigit() else 0, self.px_url.get_text().strip()),
           lambda _r: toast(self, tr("Proxy updated (terminal programs will use it from your next sign-in)")
                            if m != "none" else tr("Proxy turned off")))


# =============================== BLUETOOTH ===============================
class BluetoothPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.g = Adw.PreferencesGroup(title="Bluetooth")
        self.sw = Adw.SwitchRow(title="Bluetooth", subtitle="")
        self.sw.connect("notify::active", self.on_switch)
        self.g.add(self.sw)
        self.add(self.g)
        self.g_dev = Adw.PreferencesGroup(title=tr("Devices"))
        self.scan_btn = Gtk.Button(label=tr("Search for devices"), valign=Gtk.Align.CENTER)
        self.scan_btn.connect("clicked", lambda *_: self.scan())
        self.g_dev.set_header_suffix(self.scan_btn)
        self.add(self.g_dev)
        self.none = Adw.StatusPage(icon_name="zeta-bluetooth", title=tr("No Bluetooth adapter"),
                                   description=tr("No Bluetooth adapter was found on this computer."))
        self.none_group = Adw.PreferencesGroup()
        self.none_group.add(self.none)
        self.add(self.none_group)
        self.refresh()

    def refresh(self):
        bg(lambda: (bluetooth.adapter(), bluetooth.devices()), self._apply)

    def _apply(self, res):
        a, devs = res
        self.none_group.set_visible(a is None)
        self.g.set_visible(a is not None)
        self.g_dev.set_visible(a is not None)
        if not a:
            return
        self._setting = True
        self.sw.set_active(a["powered"])
        self.sw.set_subtitle(a["name"])
        self._setting = False
        self.scan_btn.set_sensitive(a["powered"])
        clear_group(self.g_dev, self.rows)
        if not devs:
            r = Adw.ActionRow(title=tr("No devices"),
                              subtitle=tr("Put the device in pairing mode and press “Search for devices”"))
            self.g_dev.add(r)
            self.rows.append(r)
        for d in devs:
            r = Adw.ActionRow(title=d["name"], subtitle=tr("Connected") if d["connected"] else
                              (tr("Paired") if d["paired"] else tr("Available")))
            b = Gtk.Button(label=tr("Disconnect") if d["connected"] else tr("Connect"), valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, d=d: self.toggle(d))
            r.add_suffix(b)
            if d["paired"]:
                f = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                               tooltip_text=tr("Forget"))
                f.connect("clicked", lambda _b, d=d: bg(lambda: bluetooth.forget(d["mac"]),
                                                        lambda _r: self.refresh()))
                r.add_suffix(f)
            self.g_dev.add(r)
            self.rows.append(r)

    def on_switch(self, row, _p):
        if getattr(self, "_setting", False):
            return
        bg(lambda: bluetooth.set_power(row.get_active()), lambda _r: self.refresh())

    def scan(self):
        self.scan_btn.set_sensitive(False)
        self.scan_btn.set_label(tr("Searching…"))

        def done(_r):
            self.scan_btn.set_label(tr("Search for devices"))
            self.refresh()
        bg(lambda: bluetooth.scan(8), done)

    def toggle(self, d):
        if d["connected"]:
            bg(lambda: bluetooth.disconnect(d["mac"]), lambda _r: self.refresh())
        else:
            toast(self, tr("Connecting to {name}…").format(name=d["name"]))
            bg(lambda: bluetooth.connect(d["mac"]),
               lambda ok: (toast(self, tr("Connected") if ok else tr("Connection failed")), self.refresh()))


# =============================== PRINTERS ===============================
PRINTER_STATES = {"ready": tr("Ready"), "printing": tr("Printing"), "stopped": tr("Stopped")}


class PrintersPage(Adw.PreferencesPage):
    """Printers without technical dialogs: network (Wi-Fi or cable) and USB
    printers show up on their own, are added with one click and can be tested
    right away. Rare options (manually chosen drivers, shared queues) stay in
    the advanced CUPS settings."""

    def __init__(self):
        super().__init__()
        self.rows, self.found_rows = [], []
        self._searching = False
        self._searched = False

        self.g = Adw.PreferencesGroup(title=tr("Your printers"))
        self.add(self.g)

        self.g_found = Adw.PreferencesGroup(
            title=tr("Printers found"),
            description=tr("Turn on the printer: printers on the same network as this computer "
                           "(Wi-Fi or cable) and those connected by USB show up here on their own."))
        header = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        self.search_btn = Gtk.Button(label=tr("Search again"), valign=Gtk.Align.CENTER)
        self.search_btn.connect("clicked", lambda *_: self.search())
        header.append(self.spinner)
        header.append(self.search_btn)
        self.g_found.set_header_suffix(header)
        self.add(self.g_found)

        self.g_ip = Adw.PreferencesGroup(
            title=tr("Can't find it?"),
            description=tr("Enter the printer's IP address: its display shows it in the network "
                           "settings, or it is on the configuration page the printer prints itself."))
        self.ip = Adw.EntryRow(title=tr("Printer address (e.g. 192.168.1.50)"),
                               show_apply_button=True)
        self.ip.connect("apply", lambda *_: self.add_ip())
        self.g_ip.add(self.ip)
        wifi = Adw.ActionRow(
            title=tr("Printer not on Wi-Fi yet?"),
            subtitle=tr("Connect it to the network from its control panel (Settings › Wi-Fi) or with "
                        "the router's WPS button, then press “Search again”."))
        wifi.add_prefix(Gtk.Image(icon_name="zeta-wifi"))
        self.g_ip.add(wifi)
        advanced = Adw.ActionRow(title=tr("Advanced settings"),
                                 subtitle=tr("Manually chosen driver, options and print queues"),
                                 activatable=True)
        advanced.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        advanced.connect("activated", lambda *_: _launch_detached("system-config-printer"))
        self.g_ip.add(advanced)
        self.add(self.g_ip)

        self.none = Adw.StatusPage(icon_name="zeta-printer", title=tr("Printing service not running"),
                                   description="")
        self.none_group = Adw.PreferencesGroup()
        self.none_group.add(self.none)
        self.none_group.set_visible(False)
        self.add(self.none_group)
        # the search starts when the page is opened, not when Settings
        # starts: someone opening Appearance must not wait for printers
        self.connect("map", lambda *_: self.refresh(search=not self._searched))

    # ---- list ----
    def refresh(self, search=False):
        def read():
            active = printers.service_active()
            if active:
                printers.ensure_default()
            return active, printers.manageable(), printers.listing()
        bg(read, lambda res: self._apply(res, search))

    def _apply(self, res, search):
        active, manageable, listing = res
        self.none_group.set_visible(not active or not manageable)
        for g in (self.g_found, self.g_ip):
            g.set_visible(active and manageable)
        if not active:
            self.none.set_title(tr("Printing service not running"))
            self.none.set_description(tr("CUPS is not responding. Restart the computer; if that is not enough, "
                                         "in a terminal: sudo systemctl restart cups"))
        elif not manageable:
            self.none.set_title(tr("Printer permission required"))
            self.none.set_description(tr("This user is not in the lpadmin group. In a terminal: "
                                         "sudo usermod -aG lpadmin $USER, then sign out and back in."))
        clear_group(self.g, self.rows)
        if not listing:
            r = Adw.ActionRow(title=tr("No printers"),
                              subtitle=tr("Choose one of those found below."))
            r.add_prefix(Gtk.Image(icon_name="zeta-printer"))
            self.g.add(r)
            self.rows.append(r)
        for s in listing:
            self.g.add(self._printer_row(s))
        # while printing, the status refreshes by itself (as long as the page
        # is open): "1 queued" must not linger once the job is done
        if any(s["jobs"] or s["state"] == "printing" for s in listing) and \
                not getattr(self, "_polling", False):
            self._polling = True

            def again():
                self._polling = False
                if self.get_mapped():
                    self.refresh()
                return False
            GLib.timeout_add_seconds(3, again)
        if search and active and manageable:
            self.search()

    def _printer_row(self, s):
        pieces = []
        if s["default"]:
            pieces.append(tr("Default"))
        pieces.append(PRINTER_STATES.get(s["state"], s["state"]))
        pieces.append(s["connection"])
        if s["jobs"]:
            pieces.append(tr("{n} queued").format(n=s["jobs"]))
        r = Adw.ActionRow(title=s["description"], subtitle=" · ".join(pieces), use_markup=False)
        r.add_prefix(Gtk.Image(icon_name="zeta-printer"))
        if s["state"] == "stopped":
            b = Gtk.Button(label=tr("Resume"), valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b: self._action(printers.resume, s, tr("Printer resumed")))
            r.add_suffix(b)
        if s["jobs"]:
            b = Gtk.Button(label=tr("Cancel print jobs"), valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b: self._action(printers.cancel_jobs, s, tr("Print jobs canceled")))
            r.add_suffix(b)
        test = Gtk.Button(label=tr("Test page"), valign=Gtk.Align.CENTER)
        test.connect("clicked", lambda _b: self._action(
            printers.test_page, s, tr("Test page sent to {name}").format(name=s["description"])))
        r.add_suffix(test)
        if not s["default"]:
            st = Gtk.Button(icon_name="starred-symbolic", valign=Gtk.Align.CENTER,
                            css_classes=["flat"], tooltip_text=tr("Make default"))
            st.connect("clicked", lambda _b: self._action(
                printers.set_default, s, tr("{name} is now the default").format(name=s["description"])))
            r.add_suffix(st)
        rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                        css_classes=["flat"], tooltip_text=tr("Remove"))
        rm.connect("clicked", lambda _b: self._remove(s))
        r.add_suffix(rm)
        self.rows.append(r)
        return r

    def _action(self, func, s, message, search=False):
        def done(res):
            ok, err = res
            toast(self, message if ok else tr("Failed: {error}").format(error=err or tr("CUPS error")))
            self.refresh(search=search)
        bg(lambda: func(s["name"]), done)

    def _remove(self, s):
        dlg = Adw.AlertDialog(heading=tr("Remove “{name}”?").format(name=s["description"]),
                              body=tr("You can add it again whenever you like."))
        dlg.add_response("cancel", tr("Cancel"))
        dlg.add_response("rm", tr("Remove"))
        dlg.set_response_appearance("rm", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, resp: self._action(
            printers.remove, s, tr("“{name}” removed").format(name=s["description"]), search=True)
            if resp == "rm" else None)
        dlg.present(self.get_root())

    # ---- search ----
    def search(self):
        if self._searching:
            return
        self._searching = True
        self._searched = True
        self.spinner.start()
        self.search_btn.set_sensitive(False)
        self.search_btn.set_label(tr("Searching…"))
        bg(lambda: printers.search(8), self._found)

    def _found(self, found):
        self._searching = False
        self.spinner.stop()
        self.search_btn.set_sensitive(True)
        self.search_btn.set_label(tr("Search again"))
        clear_group(self.g_found, self.found_rows)
        if not found:
            r = Adw.ActionRow(title=tr("No new printers found"),
                              subtitle=tr("Check that it is turned on and on the same network, "
                                          "or enter its address below."))
            self.g_found.add(r)
            self.found_rows.append(r)
        for t in found:
            below = t["connection"]
            if t["model"] and t["model"].lower() not in t["name"].lower():
                below += " · " + t["model"]
            r = Adw.ActionRow(title=t["name"], subtitle=below, use_markup=False)
            r.add_prefix(Gtk.Image(icon_name="zeta-printer"))
            b = Gtk.Button(label=tr("Add"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
            b.connect("clicked", lambda btn, t=t: self._add(btn, t))
            r.add_suffix(b)
            self.g_found.add(r)
            self.found_rows.append(r)

    def _add(self, btn, t):
        btn.set_sensitive(False)
        btn.set_label(tr("Adding…"))

        def done(res):
            ok, msg = res
            toast(self, msg)
            if ok:
                self.refresh(search=True)
            else:
                btn.set_sensitive(True)
                btn.set_label(tr("Add"))
        bg(lambda: printers.add(t["uri"], t["name"], t["device_id"], t["model"]), done)

    def add_ip(self):
        text = self.ip.get_text().strip()
        if not text:
            return
        self.ip.set_sensitive(False)
        toast(self, tr("Connecting to {address}…").format(address=text))

        def done(res):
            ok, msg = res
            self.ip.set_sensitive(True)
            if ok:
                self.ip.set_text("")
            toast(self, msg)
            self.refresh()
        bg(lambda: printers.add_address(text), done)


_CHILDREN = set()


def _launch_detached(prog):
    try:
        p = subprocess.Popen([prog], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _CHILDREN.add(p)                 # no zombies and no double reaping

        def finished(_pid, state, proc=p):
            proc.returncode = state
            _CHILDREN.discard(proc)
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT_IDLE, p.pid, finished)
    except OSError:
        pass


# =============================== AUDIO ===============================
class AudioPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self._upd = False
        self.out_rows, self.in_rows, self.app_rows = [], [], []

        self.g_out = Adw.PreferencesGroup(title=tr("Output"))
        self.out_vol, self.out_mute = self._volume_row(self.g_out, tr("Volume"), audio.DEFAULT_SINK)
        self.add(self.g_out)
        self.g_in = Adw.PreferencesGroup(title=tr("Input (microphone)"))
        self.in_vol, self.in_mute = self._volume_row(self.g_in, tr("Volume"), audio.DEFAULT_SOURCE)
        self.add(self.g_in)
        self.g_apps = Adw.PreferencesGroup(title=tr("Applications"),
                                           description=tr("Volume of the apps that are playing audio."))
        self.add(self.g_apps)
        self.none = Adw.PreferencesGroup()
        self.none.add(Adw.StatusPage(icon_name="zeta-volume-mute", title=tr("No sound card"),
                                     description=tr("No audio device was found. "
                                                    "In VirtualBox: Settings → Audio → “Intel HD Audio” controller.")))
        self.add(self.none)
        self.refresh()
        self._timer = GLib.timeout_add_seconds(3, self._tick)

    def _volume_row(self, group, title, target):
        row = Adw.ActionRow(title=title)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_draw_value(False)
        scale.set_size_request(260, -1)
        scale.set_valign(Gtk.Align.CENTER)
        scale.connect("value-changed", lambda s, t=target: None if self._upd
                      else audio.set_volume(s.get_value() / 100, t))
        mute = Gtk.ToggleButton(icon_name="zeta-volume", valign=Gtk.Align.CENTER, css_classes=["flat"],
                                tooltip_text=tr("Mute"))
        mute.connect("toggled", lambda b, t=target: None if self._upd else audio.set_mute(b.get_active(), t))
        row.add_suffix(scale)
        row.add_suffix(mute)
        group.add(row)
        return scale, mute

    def _tick(self):
        if not self.get_mapped():
            return True
        self.refresh()
        return True

    def refresh(self):
        bg(lambda: {"sinks": [x for x in audio.devices(audio.SINK) if x["name"] != "auto_null"],
                    "sources": [x for x in audio.devices(audio.SOURCE) if not x["name"].endswith(".monitor")],
                    "out": audio.volume(audio.DEFAULT_SINK), "in": audio.volume(audio.DEFAULT_SOURCE),
                    "apps": [(s, audio.volume(s["id"])) for s in audio.streams()]}, self._apply)

    def _apply(self, d):
        self._upd = True
        has_out, has_in = bool(d["sinks"]), bool(d["sources"])
        self.g_out.set_visible(has_out)
        self.g_in.set_visible(has_in)
        self.g_apps.set_visible(has_out and bool(d["apps"]))
        self.none.set_visible(not has_out)
        if has_out and d["out"][0] is not None:
            self.out_vol.set_value(round(d["out"][0] * 100))
            self.out_mute.set_active(d["out"][1])
            self.out_mute.set_icon_name("zeta-volume-mute" if d["out"][1] else "zeta-volume")
            self._devices(self.g_out, self.out_rows, d["sinks"])
        if has_in and d["in"][0] is not None:
            self.in_vol.set_value(round(d["in"][0] * 100))
            self.in_mute.set_active(d["in"][1])
            self.in_mute.set_icon_name("zeta-mic-off" if d["in"][1] else "zeta-mic")
            self._devices(self.g_in, self.in_rows, d["sources"])
        clear_group(self.g_apps, self.app_rows)
        for s, (v, _m) in d["apps"]:
            r = Adw.ActionRow(title=s["app"], subtitle=s["label"])
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            sc.set_draw_value(False)
            sc.set_size_request(220, -1)
            sc.set_valign(Gtk.Align.CENTER)
            sc.set_value(round((v or 0) * 100))
            sc.connect("value-changed", lambda x, i=s["id"]: audio.set_volume(x.get_value() / 100, i))
            r.add_suffix(sc)
            self.g_apps.add(r)
            self.app_rows.append(r)
        self._upd = False

    def _devices(self, group, rows, devs):
        if len(devs) < 2:
            clear_group(group, rows)
            if devs:
                r = Adw.ActionRow(title=tr("Device"), subtitle=devs[0]["label"])
                group.add(r)
                rows.append(r)
            return
        clear_group(group, rows)
        first = None
        for dv in devs:
            r = Adw.ActionRow(title=dv["label"])
            chk = Gtk.CheckButton(active=dv["default"], valign=Gtk.Align.CENTER)
            if first:
                chk.set_group(first)
            first = first or chk
            chk.connect("toggled", lambda c, i=dv["id"]: audio.set_default(i) if c.get_active() and not self._upd
                        else None)
            r.add_prefix(chk)
            r.set_activatable_widget(chk)
            group.add(r)
            rows.append(r)
