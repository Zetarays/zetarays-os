# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Impostazioni — pagine Rete, Bluetooth, Stampanti e Audio (libadwaita).

Sostituiscono le finestre generiche (nm-connection-editor, blueman, pavucontrol):
stesso aspetto del resto di ZETA RAYS. I comandi lenti girano in thread; la UI si
aggiorna con GLib.idle_add e non si blocca mai.
"""
import os
import subprocess
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from system import audio, bluetooth, network, run, stampanti  # noqa: E402


def bg(work, done=None):
    """Esegue work() in un thread e poi done(risultato) nel thread della UI."""
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


# =============================== RETE ===============================
class NetworkPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.wifi_rows, self.vpn_rows = [], []

        # Stato
        self.g_state = Adw.PreferencesGroup(title="Stato")
        self.r_conn = status_row("Connessione", "…")
        self.r_ip = status_row("Indirizzo IP", "…")
        self.r_gw = status_row("Gateway", "…")
        self.r_dns = status_row("DNS", "…")
        for r in (self.r_conn, self.r_ip, self.r_gw, self.r_dns):
            self.g_state.add(r)
        self.add(self.g_state)

        # il Wi-Fi subito dopo lo stato: e' la cosa che si usa di piu'; gli
        # indirizzi IP manuali sono per pochi e stanno sotto
        self.g_wifi = Adw.PreferencesGroup(title="Wi-Fi")
        self.sw_wifi = Adw.SwitchRow(title="Wi-Fi")
        self.sw_wifi.connect("notify::active", self.on_wifi_switch)
        self.g_wifi.add(self.sw_wifi)
        # una rete che non trasmette il nome non compare nell'elenco: si scrive a mano
        nascosta = Adw.ActionRow(title="Rete nascosta", subtitle="Non compare nell'elenco: scrivi nome e password")
        bn = Gtk.Button(label="Connetti…", valign=Gtk.Align.CENTER)
        bn.connect("clicked", lambda *_: self._chiedi_nascosta())
        nascosta.add_suffix(bn)
        self.g_wifi.add(nascosta)
        rescan = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                            tooltip_text="Cerca reti", css_classes=["flat"])
        rescan.connect("clicked", lambda *_: self.load_wifi(rescan=True))
        self.g_wifi.set_header_suffix(rescan)
        self.add(self.g_wifi)

        # Configurazione IPv4 della connessione attiva
        self.g_ip = Adw.PreferencesGroup(title="Indirizzo IPv4",
                                         description="Automatico (DHCP) va bene quasi sempre.")
        self.ip_mode = Adw.ComboRow(title="Configurazione", model=Gtk.StringList.new(["Automatica (DHCP)", "Manuale"]))
        self.ip_addr = Adw.EntryRow(title="Indirizzo / prefisso (es. 192.168.1.20/24)")
        self.ip_gw = Adw.EntryRow(title="Gateway")
        self.ip_dns = Adw.EntryRow(title="DNS (separati da spazio)")
        apply = Gtk.Button(label="Applica", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        apply.connect("clicked", lambda *_: self.apply_ip())
        self.ip_mode.connect("notify::selected", lambda *_: self._ip_sensitive())
        for r in (self.ip_mode, self.ip_addr, self.ip_gw, self.ip_dns):
            self.g_ip.add(r)
        self.g_ip.set_header_suffix(apply)
        self.add(self.g_ip)

        # Wi-Fi
        # IPv6: molte reti (e tutti gli operatori mobili moderni) lo usano, e
        # senza questi controlli l'unico modo di toccarlo era la riga di
        # comando. «Disattivato» serve a chi ha una rete che con IPv6 va in
        # confusione: è il rimedio classico, e prima non c'era.
        self.g_ip6 = Adw.PreferencesGroup(
            title="Indirizzo IPv6",
            description="Automatico va bene quasi sempre. Disattivalo solo se la rete dà problemi.")
        self.ip6_mode = Adw.ComboRow(
            title="Configurazione",
            model=Gtk.StringList.new(["Automatica", "Manuale", "Disattivato"]))
        self.ip6_addr = Adw.EntryRow(title="Indirizzo / prefisso (es. 2001:db8::5/64)")
        self.ip6_gw = Adw.EntryRow(title="Gateway")
        self.ip6_dns = Adw.EntryRow(title="DNS (separati da spazio)")
        for r in (self.ip6_mode, self.ip6_addr, self.ip6_gw, self.ip6_dns):
            self.g_ip6.add(r)
        self.ip6_mode.connect("notify::selected", lambda *_: self._ip6_sensitive())
        b6 = Gtk.Button(label="Applica", halign=Gtk.Align.END, margin_top=6,
                        css_classes=["suggested-action"])
        b6.connect("clicked", lambda *_: self.apply_ip6())
        self.g_ip6.add(b6)
        self.add(self.g_ip6)


        # Accesso remoto (SSH): acceso apre la porta 22 alla sola rete locale;
        # «Anche da internet» la apre anche da fuori (serve l'inoltro sul
        # router). Tutto passa da zeta-ssh, con la password, e resta dopo il riavvio.
        self.g_ssh = Adw.PreferencesGroup(
            title="Accesso remoto (SSH)",
            description="Per entrare in questo computer da un altro della stessa rete "
                        "(casa, ufficio). Da internet solo se lo scegli qui sotto.")
        self.sw_ssh = Adw.SwitchRow(title="Accesso remoto", subtitle="…")
        self.sw_ssh.connect("notify::active", self.on_ssh_switch)
        self.g_ssh.add(self.sw_ssh)
        self.sw_ssh_remoto = Adw.SwitchRow(
            title="Anche da internet",
            subtitle="Spento: solo dalla rete locale. Serve anche l'inoltro della porta 22 sul router.")
        self.sw_ssh_remoto.set_sensitive(False)
        self.sw_ssh_remoto.connect("notify::active", self.on_ssh_remoto_switch)
        self.g_ssh.add(self.sw_ssh_remoto)
        self.add(self.g_ssh)
        self._leggi_ssh()

        # VPN
        self.g_vpn = Adw.PreferencesGroup(title="VPN",
                                          description="WireGuard (.conf) e OpenVPN (.ovpn).")
        imp = Gtk.Button(label="Importa…", valign=Gtk.Align.CENTER)
        imp.connect("clicked", lambda *_: self.import_vpn())
        self.g_vpn.set_header_suffix(imp)
        self.vpn_empty = Adw.ActionRow(title="Nessuna VPN configurata",
                                       subtitle="Importa il file ricevuto dal tuo fornitore VPN")
        self.g_vpn.add(self.vpn_empty)
        self.add(self.g_vpn)

        # Proxy
        self.g_proxy = Adw.PreferencesGroup(title="Proxy",
                                            description="Usato da Firefox, dalle app e dal terminale.")
        self.px_mode = Adw.ComboRow(title="Modalità", model=Gtk.StringList.new(["Nessuno", "Manuale", "Automatico (PAC)"]))
        self.px_host = Adw.EntryRow(title="Server")
        self.px_port = Adw.EntryRow(title="Porta")
        self.px_url = Adw.EntryRow(title="Indirizzo del file PAC")
        papply = Gtk.Button(label="Applica", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        papply.connect("clicked", lambda *_: self.apply_proxy())
        self.px_mode.connect("notify::selected", lambda *_: self._proxy_sensitive())
        for r in (self.px_mode, self.px_host, self.px_port, self.px_url):
            self.g_proxy.add(r)
        self.g_proxy.set_header_suffix(papply)
        self.add(self.g_proxy)

        self.active_conn = None
        self.refresh()
        self.load_proxy()

    # ---- stato ----
    def refresh(self):
        def work():
            st = network.status()
            conf = {}
            if st["connected"] and st["name"]:
                out = run(["nmcli", "-t", "-f",
                           "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns,"
                           "ipv6.method,ipv6.addresses,ipv6.gateway,ipv6.dns",
                           "connection", "show", "id", st["name"]]) or ""
                for line in out.splitlines():
                    k, _, v = line.partition(":")
                    conf[k] = v
            gw = run(["ip", "route", "show", "default"]) or ""
            dns = run(["nmcli", "-t", "-f", "IP4.DNS", "device", "show", st["device"]]) if st["device"] else ""
            return st, conf, gw, dns, network.has_wifi(), network.wifi_enabled(), network.vpns()
        bg(work, self._apply_state)

    def _apply_state(self, res):
        st, conf, gw, dns, has_wifi, wifi_on, vpns = res
        kind = {"wifi": "Wi-Fi", "ethernet": "Ethernet"}.get(st["kind"], "")
        self.r_conn.set_subtitle(("%s · %s" % (kind, st["label"])) if st["connected"] else "Non connesso")
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
            metodo6 = conf.get("ipv6.method", "auto")
            self.ip6_mode.set_selected({"manual": 1, "disabled": 2, "ignore": 2}.get(metodo6, 0))
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
        scelta = self.ip6_mode.get_selected()
        if scelta == 1:
            addr = self.ip6_addr.get_text().strip()
            if addr and "/" not in addr:
                addr += "/64"
            args = ["ipv6.method", "manual", "ipv6.addresses", addr,
                    "ipv6.gateway", self.ip6_gw.get_text().strip(),
                    "ipv6.dns", self.ip6_dns.get_text().strip().replace(" ", ",")]
        elif scelta == 2:
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
        bg(work, lambda ok: (toast(self, "Configurazione IPv6 applicata" if ok else
                                   "Impossibile applicare: controlla i valori"), self.refresh()))

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
        bg(work, lambda ok: (toast(self, "Configurazione applicata" if ok else
                                   "Impossibile applicare: controlla i valori"), self.refresh()))

    # ---- Accesso remoto (SSH) ----
    def _leggi_ssh(self):
        def work():
            try:
                r = subprocess.run(["zeta-ssh", "stato"], capture_output=True, text=True, timeout=10)
                c = subprocess.run(["zeta-ssh", "config"], capture_output=True, text=True, timeout=10)
                return r.returncode, r.stdout.strip(), "SSH_REMOTE_ACCESS=true" in c.stdout
            except (OSError, subprocess.SubprocessError) as e:
                return 9, str(e), False
        bg(work, self._mostra_ssh)

    def _mostra_ssh(self, res):
        rc, testo, remoto = res
        acceso = rc == 0
        righe = [l.strip() for l in testo.splitlines() if l.strip().startswith("dalla rete locale:")]
        if acceso:
            sotto = "Acceso. " + ("  ".join(l.split(":", 1)[1].strip() for l in righe) or "Porta 22 aperta alla rete locale.")
        elif rc == 9:
            sotto = "Non disponibile: " + testo[:80]
        elif rc == 2:
            sotto = "A metà: spegnilo e riaccendilo."
        else:
            sotto = "Spento."
        self._ssh_aggiorna = True
        self.sw_ssh.set_active(acceso)
        self.sw_ssh_remoto.set_active(acceso and remoto)
        self._ssh_aggiorna = False
        self.sw_ssh.set_subtitle(sotto)
        dal_vivo = os.path.exists("/run/live/medium")
        self.sw_ssh_remoto.set_sensitive(acceso and not dal_vivo)
        if dal_vivo:
            self.sw_ssh_remoto.set_subtitle("Non disponibile nella sessione dal vivo (password «zeta» nota a tutti).")
        elif acceso and remoto:
            self.sw_ssh_remoto.set_subtitle("Aperto anche da internet. Root non entra; troppi tentativi "
                                            "dallo stesso indirizzo vengono scartati.")
        else:
            self.sw_ssh_remoto.set_subtitle("Spento: solo dalla rete locale. Serve anche l'inoltro "
                                            "della porta 22 sul router.")

    def on_ssh_remoto_switch(self, row, _p):
        if getattr(self, "_ssh_aggiorna", False):
            return
        apri = row.get_active()
        self.sw_ssh_remoto.set_subtitle("Apertura…" if apri else "Chiusura…")

        def work():
            try:
                r = subprocess.run(["pkexec", "zeta-ssh", "remoto", "attiva" if apri else "disattiva"],
                                   capture_output=True, text=True, timeout=120)
                return r.returncode, (r.stdout + r.stderr).strip()
            except (OSError, subprocess.SubprocessError) as e:
                return 1, str(e)

        def fatto(res):
            rc, testo = res
            if rc == 0:
                toast(self, "SSH aperto anche da internet" if apri else "SSH solo dalla rete locale")
            elif rc in (126, 127):
                toast(self, "Operazione annullata")
            else:
                toast(self, "Non riuscito: " + (testo.splitlines()[-1] if testo else "errore"))
            self._leggi_ssh()
        bg(work, fatto)

    def on_ssh_switch(self, row, _p):
        if getattr(self, "_ssh_aggiorna", False):
            return
        accendi = row.get_active()
        self.sw_ssh.set_subtitle("Accensione…" if accendi else "Spegnimento…")

        def work():
            # pkexec chiede la password dell'amministratore (cambia il firewall)
            try:
                r = subprocess.run(["pkexec", "zeta-ssh", "attiva" if accendi else "disattiva"],
                                   capture_output=True, text=True, timeout=120)
                return r.returncode, (r.stdout + r.stderr).strip()
            except (OSError, subprocess.SubprocessError) as e:
                return 1, str(e)

        def fatto(res):
            rc, testo = res
            if rc == 0:
                toast(self, "Accesso remoto acceso" if accendi else "Accesso remoto spento")
            elif rc in (126, 127):
                toast(self, "Operazione annullata")
            else:
                toast(self, "Non riuscito: " + (testo.splitlines()[-1] if testo else "errore"))
            self._leggi_ssh()          # si mostra lo stato vero, non quello chiesto
        bg(work, fatto)

    # ---- Wi-Fi ----
    def on_wifi_switch(self, row, _p):
        if getattr(self, "_setting_wifi", False):
            return
        bg(lambda: network.set_wifi(row.get_active()), lambda _r: GLib.timeout_add(1200, self.refresh))

    def load_wifi(self, rescan=False):
        bg(lambda: (network.wifi_networks(rescan), network.known_wifi()), self.show_wifi)

    def show_wifi(self, dati):
        nets, salvate = dati
        clear_group(self.g_wifi, self.wifi_rows)
        if not nets:
            r = Adw.ActionRow(title="Nessuna rete trovata")
            self.g_wifi.add(r)
            self.wifi_rows.append(r)
        in_corso = getattr(self, "_wifi_in_corso", None)
        for n in nets[:12]:
            lvl = 3 if n["signal"] > 66 else 2 if n["signal"] > 33 else 1
            nota = ("Connessa" if n["active"] else "Connessione…" if n["ssid"] == in_corso else
                    "Salvata" if n["ssid"] in salvate else "Protetta" if n["secure"] else "Aperta")
            r = Adw.ActionRow(title=n["ssid"], subtitle=nota)
            r.add_prefix(Gtk.Image(icon_name="zeta-wifi-%d" % lvl))
            if n["ssid"] in salvate and n["secure"]:
                cp = Gtk.Button(icon_name="dialog-password-symbolic", valign=Gtk.Align.CENTER,
                                css_classes=["flat"], tooltip_text="Cambia password")
                cp.connect("clicked", lambda _b, n=n: self._chiedi_password(n["ssid"]))
                r.add_suffix(cp)
            if n["ssid"] in salvate:
                dm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                css_classes=["flat"], tooltip_text="Dimentica rete")
                dm.connect("clicked", lambda _b, n=n: self._dimentica(n["ssid"]))
                r.add_suffix(dm)
            if not n["active"]:
                b = Gtk.Button(label="Connetti", valign=Gtk.Align.CENTER,
                               sensitive=in_corso is None)
                b.connect("clicked", lambda _b, n=n, s=salvate: self.connect_wifi(n, s))
                r.add_suffix(b)
            self.g_wifi.add(r)
            self.wifi_rows.append(r)

    def connect_wifi(self, n, salvate=()):
        if n["secure"] and n["ssid"] not in salvate:
            self._chiedi_password(n["ssid"])
        else:
            self._do_connect(n["ssid"], None)

    def _chiedi_password(self, ssid, errore=""):
        """Chiede la password; dopo un tentativo fallito la richiede con il
        motivo scritto sopra, invece di lasciare l'utente senza risposta."""
        dlg = Adw.AlertDialog(heading="Password di «%s»" % ssid, body=errore)
        entry = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Annulla")
        dlg.add_response("ok", "Connetti")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")
        dlg.set_close_response("cancel")

        def risposta(_d, resp):
            pw = entry.get_text()
            if resp != "ok":
                return
            if not pw:
                GLib.idle_add(self._chiedi_password, ssid, "Scrivi la password della rete.")
                return
            self._do_connect(ssid, pw)
        dlg.connect("response", risposta)
        dlg.present(self.get_root())
        entry.grab_focus()
        return False

    def _chiedi_nascosta(self, errore=""):
        dlg = Adw.AlertDialog(heading="Rete nascosta", body=errore)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        nome = Gtk.Entry(placeholder_text="Nome della rete (SSID)", activates_default=True)
        pw = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True,
                               placeholder_text="Password (vuota se la rete è aperta)")
        box.append(nome)
        box.append(pw)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Annulla")
        dlg.add_response("ok", "Connetti")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")
        dlg.set_close_response("cancel")

        def risposta(_d, resp):
            if resp != "ok":
                return
            ssid = nome.get_text().strip()
            if not ssid:
                GLib.idle_add(self._chiedi_nascosta, "Scrivi il nome della rete.")
                return
            self._do_connect(ssid, pw.get_text() or None, nascosta=True)
        dlg.connect("response", risposta)
        dlg.present(self.get_root())
        nome.grab_focus()
        return False

    def _do_connect(self, ssid, pw, nascosta=False):
        if getattr(self, "_wifi_in_corso", None):
            return                                   # un tentativo alla volta
        self._wifi_in_corso = ssid
        toast(self, "Connessione a «%s»…" % ssid)
        self.load_wifi()

        def fatto(res):
            ok, msg, motivo = res
            self._wifi_in_corso = None
            toast(self, msg)
            self.refresh()
            self._rileggi_dopo()
            if motivo == "password" and nascosta:
                self._chiedi_nascosta(msg)
            elif motivo == "password":
                self._chiedi_password(ssid, msg)
        bg(lambda: network.connect_wifi_esito(ssid, pw, nascosta=nascosta), fatto)

    def _rileggi_dopo(self):
        """NetworkManager finisce di collegare o scollegare un attimo dopo aver
        risposto: l'elenco si rilegge di nuovo, altrimenti resta «Connessa»."""
        GLib.timeout_add(2500, lambda: (self.load_wifi(), False)[1])

    def _dimentica(self, ssid):
        dlg = Adw.AlertDialog(heading="Dimenticare «%s»?" % ssid,
                              body="La password salvata verrà cancellata; per riconnetterti "
                                   "dovrai inserirla di nuovo.")
        dlg.add_response("cancel", "Annulla")
        dlg.add_response("ok", "Dimentica")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, resp: bg(
            lambda: network.forget_wifi(ssid),
            lambda ok: (toast(self, ("«%s» dimenticata" if ok else "Non riesco a dimenticare «%s»") % ssid),
                        self.refresh(), self._rileggi_dopo())) if resp == "ok" else None)
        dlg.present(self.get_root())

    # ---- VPN ----
    def show_vpns(self, vpns):
        clear_group(self.g_vpn, self.vpn_rows)
        self.vpn_empty.set_visible(not vpns)
        for v in vpns:
            r = Adw.ActionRow(title=v["name"], subtitle=v["type"] + (" · attiva" if v["active"] else ""))
            r.add_prefix(Gtk.Image(icon_name="zeta-vpn"))
            sw = Gtk.Switch(active=v["active"], valign=Gtk.Align.CENTER)
            sw.connect("state-set", lambda _s, on, v=v: self.set_vpn(v, on))
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                            css_classes=["flat"], tooltip_text="Rimuovi")
            rm.connect("clicked", lambda _b, v=v: self.remove_vpn(v))
            r.add_suffix(sw)
            r.add_suffix(rm)
            self.g_vpn.add(r)
            self.vpn_rows.append(r)

    def set_vpn(self, v, on):
        bg(lambda: network.set_vpn(v["uuid"], on),
           lambda ok: (toast(self, ("VPN %s %s" % (v["name"], "attivata" if on else "disattivata"))
                             if ok else "Impossibile %s la VPN" % ("attivare" if on else "disattivare")),
                       self.refresh()))
        return False

    def remove_vpn(self, v):
        dlg = Adw.AlertDialog(heading="Rimuovere la VPN «%s»?" % v["name"],
                              body="La configurazione verrà eliminata da questo computer.")
        dlg.add_response("cancel", "Annulla")
        dlg.add_response("rm", "Rimuovi")
        dlg.set_response_appearance("rm", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response", lambda _d, r: bg(lambda: network.remove_connection(v["uuid"]),
                                                 lambda _ok: self.refresh()) if r == "rm" else None)
        dlg.present(self.get_root())

    def import_vpn(self):
        filt = Gtk.FileFilter(name="Configurazioni VPN")
        filt.add_pattern("*.conf")
        filt.add_pattern("*.ovpn")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filt)
        dlg = Gtk.FileDialog(title="Importa VPN", filters=filters)

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
           lambda _r: toast(self, "Proxy aggiornato (i programmi da terminale lo useranno al prossimo accesso)"
                            if m != "none" else "Proxy disattivato"))


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
        self.g_dev = Adw.PreferencesGroup(title="Dispositivi")
        self.scan_btn = Gtk.Button(label="Cerca dispositivi", valign=Gtk.Align.CENTER)
        self.scan_btn.connect("clicked", lambda *_: self.scan())
        self.g_dev.set_header_suffix(self.scan_btn)
        self.add(self.g_dev)
        self.none = Adw.StatusPage(icon_name="zeta-bluetooth", title="Nessun adattatore Bluetooth",
                                   description="Su questo computer non è stato trovato un adattatore Bluetooth.")
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
            r = Adw.ActionRow(title="Nessun dispositivo",
                              subtitle="Metti il dispositivo in modalità associazione e premi «Cerca dispositivi»")
            self.g_dev.add(r)
            self.rows.append(r)
        for d in devs:
            r = Adw.ActionRow(title=d["name"], subtitle="Connesso" if d["connected"] else
                              ("Associato" if d["paired"] else "Disponibile"))
            b = Gtk.Button(label="Disconnetti" if d["connected"] else "Connetti", valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, d=d: self.toggle(d))
            r.add_suffix(b)
            if d["paired"]:
                f = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                               tooltip_text="Dimentica")
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
        self.scan_btn.set_label("Ricerca…")

        def done(_r):
            self.scan_btn.set_label("Cerca dispositivi")
            self.refresh()
        bg(lambda: bluetooth.scan(8), done)

    def toggle(self, d):
        if d["connected"]:
            bg(lambda: bluetooth.disconnect(d["mac"]), lambda _r: self.refresh())
        else:
            toast(self, "Connessione a %s…" % d["name"])
            bg(lambda: bluetooth.connect(d["mac"]),
               lambda ok: (toast(self, "Connesso" if ok else "Connessione non riuscita"), self.refresh()))


# =============================== STAMPANTI ===============================
STATI_STAMPANTE = {"pronta": "Pronta", "stampa": "Sta stampando", "ferma": "Ferma"}


class PrintersPage(Adw.PreferencesPage):
    """Stampanti senza finestre tecniche: quelle in rete (Wi-Fi o cavo) e
    USB compaiono da sole, si aggiungono con un clic e si provano subito.
    Le opzioni rare (driver a mano, code condivise) restano nelle
    impostazioni avanzate di CUPS."""

    def __init__(self):
        super().__init__()
        self.rows, self.found_rows = [], []
        self._cercando = False
        self._cercato = False

        self.g = Adw.PreferencesGroup(title="Le tue stampanti")
        self.add(self.g)

        self.g_found = Adw.PreferencesGroup(
            title="Stampanti trovate",
            description="Accendi la stampante: quelle collegate alla stessa rete del "
                        "computer (Wi-Fi o cavo) e quelle con il cavo USB compaiono qui da sole.")
        testa = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        self.cerca_btn = Gtk.Button(label="Cerca di nuovo", valign=Gtk.Align.CENTER)
        self.cerca_btn.connect("clicked", lambda *_: self.cerca())
        testa.append(self.spinner)
        testa.append(self.cerca_btn)
        self.g_found.set_header_suffix(testa)
        self.add(self.g_found)

        self.g_ip = Adw.PreferencesGroup(
            title="Non la trovi?",
            description="Scrivi l'indirizzo IP della stampante: lo mostra il suo display "
                        "nelle impostazioni di rete, oppure la pagina di configurazione che stampa da sola.")
        self.ip = Adw.EntryRow(title="Indirizzo della stampante (es. 192.168.1.50)",
                               show_apply_button=True)
        self.ip.connect("apply", lambda *_: self.aggiungi_ip())
        self.g_ip.add(self.ip)
        wifi = Adw.ActionRow(
            title="La stampante non è ancora in Wi-Fi?",
            subtitle="Collegala alla rete dal suo pannello (Impostazioni › Wi-Fi) o con il "
                     "tasto WPS del router, poi premi «Cerca di nuovo».")
        wifi.add_prefix(Gtk.Image(icon_name="zeta-wifi"))
        self.g_ip.add(wifi)
        avanzate = Adw.ActionRow(title="Impostazioni avanzate",
                                 subtitle="Driver scelto a mano, opzioni e code di stampa",
                                 activatable=True)
        avanzate.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        avanzate.connect("activated", lambda *_: _avvia_staccato("system-config-printer"))
        self.g_ip.add(avanzate)
        self.add(self.g_ip)

        self.none = Adw.StatusPage(icon_name="zeta-printer", title="Servizio di stampa non attivo",
                                   description="")
        self.none_group = Adw.PreferencesGroup()
        self.none_group.add(self.none)
        self.none_group.set_visible(False)
        self.add(self.none_group)
        # la ricerca parte quando la pagina si apre, non all'avvio delle
        # Impostazioni: chi apre l'Aspetto non deve aspettare le stampanti
        self.connect("map", lambda *_: self.refresh(cerca=not self._cercato))

    # ---- elenco ----
    def refresh(self, cerca=False):
        def leggi():
            attivo = stampanti.servizio_attivo()
            if attivo:
                stampanti.assicura_predefinita()
            return attivo, stampanti.gestibili(), stampanti.elenco()
        bg(leggi, lambda res: self._apply(res, cerca))

    def _apply(self, res, cerca):
        attivo, gestibili, elenco = res
        self.none_group.set_visible(not attivo or not gestibili)
        for g in (self.g_found, self.g_ip):
            g.set_visible(attivo and gestibili)
        if not attivo:
            self.none.set_title("Servizio di stampa non attivo")
            self.none.set_description("CUPS non risponde. Riavvia il computer; se non basta, "
                                      "da terminale: sudo systemctl restart cups")
        elif not gestibili:
            self.none.set_title("Serve il permesso per le stampanti")
            self.none.set_description("Questo utente non è nel gruppo lpadmin. Da terminale: "
                                      "sudo usermod -aG lpadmin $USER, poi esci e rientra.")
        clear_group(self.g, self.rows)
        if not elenco:
            r = Adw.ActionRow(title="Nessuna stampante",
                              subtitle="Scegline una tra quelle trovate qui sotto.")
            r.add_prefix(Gtk.Image(icon_name="zeta-printer"))
            self.g.add(r)
            self.rows.append(r)
        for s in elenco:
            self.g.add(self._riga_stampante(s))
        # mentre stampa, lo stato si aggiorna da solo (finche' la pagina e'
        # aperta): «1 in coda» non deve restare quando la stampa e' finita
        if any(s["lavori"] or s["stato"] == "stampa" for s in elenco) and \
                not getattr(self, "_segue", False):
            self._segue = True

            def ancora():
                self._segue = False
                if self.get_mapped():
                    self.refresh()
                return False
            GLib.timeout_add_seconds(3, ancora)
        if cerca and attivo and gestibili:
            self.cerca()

    def _riga_stampante(self, s):
        parti = []
        if s["predefinita"]:
            parti.append("Predefinita")
        parti.append(STATI_STAMPANTE.get(s["stato"], s["stato"]))
        parti.append(s["collegamento"])
        if s["lavori"]:
            parti.append("%d in coda" % s["lavori"])
        r = Adw.ActionRow(title=s["descrizione"], subtitle=" · ".join(parti))
        r.add_prefix(Gtk.Image(icon_name="zeta-printer"))
        if s["stato"] == "ferma":
            b = Gtk.Button(label="Riprendi", valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b: self._azione(stampanti.riprendi, s, "Stampante ripresa"))
            r.add_suffix(b)
        if s["lavori"]:
            b = Gtk.Button(label="Annulla stampe", valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b: self._azione(stampanti.annulla_lavori, s, "Stampe annullate"))
            r.add_suffix(b)
        prova = Gtk.Button(label="Pagina di prova", valign=Gtk.Align.CENTER)
        prova.connect("clicked", lambda _b: self._azione(
            stampanti.pagina_di_prova, s, "Pagina di prova inviata a %s" % s["descrizione"]))
        r.add_suffix(prova)
        if not s["predefinita"]:
            st = Gtk.Button(icon_name="starred-symbolic", valign=Gtk.Align.CENTER,
                            css_classes=["flat"], tooltip_text="Usala come predefinita")
            st.connect("clicked", lambda _b: self._azione(
                stampanti.imposta_predefinita, s, "%s è la predefinita" % s["descrizione"]))
            r.add_suffix(st)
        rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                        css_classes=["flat"], tooltip_text="Rimuovi")
        rm.connect("clicked", lambda _b: self._rimuovi(s))
        r.add_suffix(rm)
        self.rows.append(r)
        return r

    def _azione(self, funzione, s, messaggio, cerca=False):
        def fatto(res):
            ok, err = res
            toast(self, messaggio if ok else "Non riuscito: %s" % (err or "errore di CUPS"))
            self.refresh(cerca=cerca)
        bg(lambda: funzione(s["nome"]), fatto)

    def _rimuovi(self, s):
        dlg = Adw.AlertDialog(heading="Rimuovere «%s»?" % s["descrizione"],
                              body="Potrai aggiungerla di nuovo quando vuoi.")
        dlg.add_response("cancel", "Annulla")
        dlg.add_response("rm", "Rimuovi")
        dlg.set_response_appearance("rm", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, resp: self._azione(
            stampanti.rimuovi, s, "«%s» rimossa" % s["descrizione"], cerca=True)
            if resp == "rm" else None)
        dlg.present(self.get_root())

    # ---- ricerca ----
    def cerca(self):
        if self._cercando:
            return
        self._cercando = True
        self._cercato = True
        self.spinner.start()
        self.cerca_btn.set_sensitive(False)
        self.cerca_btn.set_label("Ricerca…")
        bg(lambda: stampanti.cerca(8), self._trovate)

    def _trovate(self, trovate):
        self._cercando = False
        self.spinner.stop()
        self.cerca_btn.set_sensitive(True)
        self.cerca_btn.set_label("Cerca di nuovo")
        clear_group(self.g_found, self.found_rows)
        if not trovate:
            r = Adw.ActionRow(title="Nessuna nuova stampante trovata",
                              subtitle="Controlla che sia accesa e sulla stessa rete, "
                                       "oppure scrivi il suo indirizzo qui sotto.")
            self.g_found.add(r)
            self.found_rows.append(r)
        for t in trovate:
            sotto = t["collegamento"]
            if t["modello"] and t["modello"].lower() not in t["nome"].lower():
                sotto += " · " + t["modello"]
            r = Adw.ActionRow(title=t["nome"], subtitle=sotto)
            r.add_prefix(Gtk.Image(icon_name="zeta-printer"))
            b = Gtk.Button(label="Aggiungi", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
            b.connect("clicked", lambda btn, t=t: self._aggiungi(btn, t))
            r.add_suffix(b)
            self.g_found.add(r)
            self.found_rows.append(r)

    def _aggiungi(self, btn, t):
        btn.set_sensitive(False)
        btn.set_label("Aggiunta…")

        def fatto(res):
            ok, msg = res
            toast(self, msg)
            if ok:
                self.refresh(cerca=True)
            else:
                btn.set_sensitive(True)
                btn.set_label("Aggiungi")
        bg(lambda: stampanti.aggiungi(t["uri"], t["nome"], t["device_id"], t["modello"]), fatto)

    def aggiungi_ip(self):
        testo = self.ip.get_text().strip()
        if not testo:
            return
        self.ip.set_sensitive(False)
        toast(self, "Collegamento a %s…" % testo)

        def fatto(res):
            ok, msg = res
            self.ip.set_sensitive(True)
            if ok:
                self.ip.set_text("")
            toast(self, msg)
            self.refresh()
        bg(lambda: stampanti.aggiungi_indirizzo(testo), fatto)


def _avvia_staccato(prog):
    try:
        subprocess.Popen([prog], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


# =============================== AUDIO ===============================
class AudioPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self._upd = False
        self.out_rows, self.in_rows, self.app_rows = [], [], []

        self.g_out = Adw.PreferencesGroup(title="Uscita")
        self.out_vol, self.out_mute = self._volume_row(self.g_out, "Volume", audio.DEFAULT_SINK)
        self.add(self.g_out)
        self.g_in = Adw.PreferencesGroup(title="Ingresso (microfono)")
        self.in_vol, self.in_mute = self._volume_row(self.g_in, "Volume", audio.DEFAULT_SOURCE)
        self.add(self.g_in)
        self.g_apps = Adw.PreferencesGroup(title="Applicazioni",
                                           description="Volume delle app che stanno riproducendo audio.")
        self.add(self.g_apps)
        self.none = Adw.PreferencesGroup()
        self.none.add(Adw.StatusPage(icon_name="zeta-volume-mute", title="Nessuna scheda audio",
                                     description="Non è stato trovato un dispositivo audio. "
                                                 "In VirtualBox: Impostazioni → Audio → controller «Intel HD Audio»."))
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
                                tooltip_text="Silenzia")
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
                r = Adw.ActionRow(title="Dispositivo", subtitle=devs[0]["label"])
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
