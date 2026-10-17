# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Settings: Software Update.

Check, download and install the updates of the system packages without a
terminal, like the update page of other systems. All the work goes through
PackageKit (system/software_update.py): this page runs as the user, never as
root, and the administrator password is asked by the session's polkit agent
only when installing.

Opening the page does not touch the network: it shows what the package
lists already on disk say. The software sources are contacted only when the
user clicks "Check for Updates" (or turns on the weekly reminder).
"""
import subprocess
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import ntr, tr  # noqa: E402
from system import power  # noqa: E402
from system import software_update as su  # noqa: E402


def _toast(widget, text):
    root = widget.get_root()
    if hasattr(root, "toast"):
        root.toast(text)


def _spawn(*cmd):
    try:
        subprocess.Popen(list(cmd), start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


class SoftwareUpdatePage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.session = su.Session() if su.available() else None
        self.updates = []
        self.update_rows = []
        self.checks = {}                     # package id -> Gtk.CheckButton
        self.info = {}
        self.phase = ""
        self.loaded = False
        self.download_total = 0

        # --- live session: whatever is installed is lost at restart
        if su.is_live():
            g_live = Adw.PreferencesGroup()
            live = Adw.ActionRow(
                title=tr("You are using ZETA RAYS from the installation media"),
                subtitle=tr("Updates installed now are lost when the computer restarts. "
                            "Install ZETA RAYS to keep them."))
            live.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
            g_live.add(live)
            self.add(g_live)

        # --- status
        self.g_status = Adw.PreferencesGroup(title=tr("Software Update"))
        self.b_check = Gtk.Button(label=tr("Check for Updates"), valign=Gtk.Align.CENTER)
        self.b_check.connect("clicked", lambda *_: self.check(refresh=True))
        self.g_status.set_header_suffix(self.b_check)

        self.r_state = Adw.ActionRow(title=tr("Reading the list of updates…"))
        self.r_state.set_subtitle_selectable(True)
        self.state_icon = Gtk.Image(icon_name="emblem-synchronizing-symbolic", pixel_size=32)
        self.r_state.add_prefix(self.state_icon)
        self.g_status.add(self.r_state)

        # progress: bar, current step, Cancel
        self.r_progress = Adw.ActionRow(title=tr("Preparing…"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                      width_request=180)
        self.bar = Gtk.ProgressBar(show_text=False)
        box.append(self.bar)
        self.r_progress.add_suffix(box)
        self.b_cancel = Gtk.Button(label=tr("Cancel"), valign=Gtk.Align.CENTER)
        self.b_cancel.connect("clicked", lambda *_: self.cancel())
        self.r_progress.add_suffix(self.b_cancel)
        self.r_progress.set_visible(False)
        self.g_status.add(self.r_progress)

        # what went wrong, word for word (PackageKit / apt), for whoever helps
        self.r_detail = Adw.ExpanderRow(title=tr("Details"))
        self.detail_label = Gtk.Label(xalign=0, wrap=True, selectable=True,
                                      css_classes=["caption", "monospace"],
                                      margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        self.r_detail.add_row(self.detail_label)
        self.r_detail.set_visible(False)
        self.g_status.add(self.r_detail)

        self.r_restart = Adw.ActionRow(
            title=tr("Restart required"),
            subtitle=tr("Restart the computer to finish installing the updates."))
        self.r_restart.add_prefix(Gtk.Image(icon_name="system-reboot-symbolic"))
        b_restart = Gtk.Button(label=tr("Restart"), valign=Gtk.Align.CENTER,
                               css_classes=["suggested-action"])
        b_restart.connect("clicked", lambda *_: self.ask_restart())
        self.r_restart.add_suffix(b_restart)
        self.r_restart.set_visible(False)
        self.g_status.add(self.r_restart)

        # an installation left half done (dpkg): PackageKit's "repair system"
        self.r_repair = Adw.ActionRow(title=tr("The package system needs a repair"))
        self.r_repair.set_subtitle_selectable(True)
        self.r_repair.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
        self.b_repair = Gtk.Button(label=tr("Repair Now"), valign=Gtk.Align.CENTER,
                                   css_classes=["suggested-action"])
        self.b_repair.connect("clicked", lambda *_: self.repair())
        self.r_repair.add_suffix(self.b_repair)
        self.r_repair.set_visible(False)
        self.g_status.add(self.r_repair)

        self.r_last_check = Adw.ActionRow(title=tr("Last check"))
        self.l_last_check = Gtk.Label(css_classes=["dim-label"])
        self.r_last_check.add_suffix(self.l_last_check)
        self.g_status.add(self.r_last_check)
        self.r_last_update = Adw.ActionRow(title=tr("Last successful update"))
        self.l_last_update = Gtk.Label(css_classes=["dim-label"])
        self.r_last_update.add_suffix(self.l_last_update)
        self.g_status.add(self.r_last_update)
        self.add(self.g_status)

        # --- available updates
        self.g_updates = Adw.PreferencesGroup(title=tr("Available updates"))
        self.b_install = Gtk.Button(label=tr("Update All"), valign=Gtk.Align.CENTER,
                                    css_classes=["suggested-action"])
        self.b_install.connect("clicked", lambda *_: self.install())
        self.g_updates.set_header_suffix(self.b_install)
        self.r_held = Adw.ActionRow(title=tr("Held back"))
        self.r_held.set_subtitle_selectable(True)
        self.r_held.set_visible(False)
        self.g_updates.add(self.r_held)
        self.g_updates.set_visible(False)
        self.add(self.g_updates)

        # --- options
        g_opt = Adw.PreferencesGroup(title=tr("Options"))
        # automatic security updates (unattended-upgrades, security archive only)
        self.sw_auto = Adw.SwitchRow(
            title=tr("Install security updates automatically"),
            subtitle=tr("Every day, in the background, only security fixes. The computer is "
                        "never restarted without you."))
        self._auto_guard = False
        self.sw_auto.connect("notify::active", self.on_auto)
        self.r_last_auto = Adw.ActionRow(title=tr("Last automatic update"))
        self.l_last_auto = Gtk.Label(css_classes=["dim-label"])
        self.r_last_auto.add_suffix(self.l_last_auto)
        if not su.auto_updates_supported():
            self.sw_auto.set_visible(False)
            self.r_last_auto.set_visible(False)
        elif su.is_live():
            self.sw_auto.set_sensitive(False)
            self.sw_auto.set_subtitle(tr("Not available in the live session: install ZETA RAYS first."))
        g_opt.add(self.sw_auto)
        g_opt.add(self.r_last_auto)
        self.sw_reminder = Adw.SwitchRow(
            title=tr("Weekly reminder"),
            subtitle=tr("A notification when updates are available. Nothing is installed "
                        "without you."))
        self.sw_reminder.set_active(su.reminder_enabled())
        self.sw_reminder.connect("notify::active", self.on_reminder)
        g_opt.add(self.sw_reminder)
        synaptic = Adw.ActionRow(
            title=tr("Advanced: Synaptic Package Manager"),
            subtitle=tr("Every package, the software sources and repairs, for experts"),
            activatable=True)
        synaptic.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        synaptic.connect("activated", lambda *_: _spawn("synaptic-pkexec"))
        g_opt.add(synaptic)
        self.add(g_opt)

        # --- footnote
        note = Adw.PreferencesGroup(
            description=tr("Updates of the apps and system packages are installed from the "
                           "official software sources, checked with their digital signatures. "
                           "ZETA RAYS system components (desktop, Settings, ZETA) are not "
                           "packages: they are updated with new releases of ZETA RAYS."))
        self.add(note)

        if self.session is None:
            self._set_state(tr("Software Update is not available"),
                            tr("The update service (PackageKit) is not installed. Use "
                               "“Advanced: Synaptic Package Manager”."),
                            "dialog-error-symbolic")
            self.b_check.set_sensitive(False)
        # nothing slow while Settings opens: the page loads when first shown
        self.connect("map", self._on_map)

    # ------------------------------------------------------------ state
    def _set_state(self, title, subtitle="", icon=None):
        self.r_state.set_title(GLib.markup_escape_text(title))
        self.r_state.set_subtitle(GLib.markup_escape_text(subtitle or ""))
        if icon:
            self.state_icon.set_from_icon_name(icon)

    def _set_detail(self, text):
        text = (text or "").strip()
        self.detail_label.set_label(text[:4000])
        self.r_detail.set_visible(bool(text))
        self.r_detail.set_expanded(False)

    def _on_map(self, *_):
        if self.loaded:
            return
        self.loaded = True
        self._load_summary(then=lambda: self.check(refresh=False) if self.session else None)

    def _load_summary(self, then=None):
        """Dates and restart flag (reads apt's history: in a thread)."""
        def work():
            try:
                return su.summary()
            except Exception:                    # never break the page for a date
                return {}

        def done(info):
            self.info = info or {}
            self.l_last_check.set_label(su.format_date(self.info.get("last_check")))
            self.l_last_update.set_label(su.format_date(self.info.get("last_success")))
            self.r_restart.set_visible(bool(self.info.get("restart")))
            self.l_last_auto.set_label(su.format_date(self.info.get("last_automatic")))
            if self.info.get("auto") is not None:
                self._auto_guard = True
                self.sw_auto.set_active(bool(self.info["auto"]))
                self._auto_guard = False
            if then:
                then()
            return False

        threading.Thread(target=lambda: GLib.idle_add(done, work()), daemon=True).start()

    def _busy(self, busy, cancellable=True):
        self.b_check.set_sensitive(not busy and self.session is not None)
        self.b_install.set_sensitive(not busy and bool(self._selected()))
        self.b_repair.set_sensitive(not busy)
        for c in self.checks.values():
            c.set_sensitive(not busy)
        self.r_progress.set_visible(busy)
        self.b_cancel.set_visible(cancellable)
        self.b_cancel.set_sensitive(True)
        if busy:
            self.bar.set_fraction(0)
            self.r_progress.set_title(tr("Preparing…"))
            self._pulse_id = GLib.timeout_add(150, self._pulse)
        elif getattr(self, "_pulse_id", None):
            GLib.source_remove(self._pulse_id)
            self._pulse_id = None

    def _pulse(self):
        if self._fraction is None:
            self.bar.pulse()
        return True

    _fraction = None
    _pulse_id = None

    def _on_progress(self, p):
        text = p.text or tr("Preparing…")
        if self.phase == "local" and not p.waiting_for_lock:
            text = tr("Reading the list of updates…")     # no network involved
        self.r_progress.set_title(GLib.markup_escape_text(text))
        fraction = p.fraction
        if self.phase == "download" and self.download_total and p.remaining is not None:
            fraction = max(0.0, min(1.0, 1 - p.remaining / self.download_total))
        self._fraction = None if p.waiting_for_lock else fraction
        if self._fraction is not None:
            self.bar.set_fraction(self._fraction)
        # PackageKit says when stopping is safe: never while dpkg is installing
        self.b_cancel.set_sensitive(p.can_cancel)

    def cancel(self):
        if self.session is not None:
            self.b_cancel.set_sensitive(False)
            self.r_progress.set_title(tr("Cancelling…"))
            self.session.cancel()

    # ------------------------------------------------------------ check
    def check(self, refresh=True):
        if self.session is None or self.session.busy:
            return
        self._set_detail("")
        if refresh:
            self._set_state(tr("Checking for updates…"), tr("Contacting the software sources."),
                            "emblem-synchronizing-symbolic")
        else:
            self._set_state(tr("Reading the list of updates…"), "", "emblem-synchronizing-symbolic")
        self.phase = "check" if refresh else "local"
        self._busy(True)
        self.session.check(self._on_progress, lambda o: self._checked(o, refresh), refresh=refresh)

    def _show_repair(self, broken, force=False):
        self.info["broken"] = list(broken)
        if broken:
            self.r_repair.set_subtitle(GLib.markup_escape_text(
                tr("An installation was left incomplete: {names}.").format(
                    names=", ".join(broken[:6]) + ("…" if len(broken) > 6 else ""))))
        else:
            self.r_repair.set_subtitle(tr("An installation was left incomplete."))
        self.r_repair.set_visible(bool(broken) or force)

    def repair(self):
        if self.session is None or self.session.busy:
            return
        self._set_detail("")
        self._set_state(tr("Repairing…"), tr("Finishing the installation that was left incomplete."),
                        "emblem-synchronizing-symbolic")
        self.phase = "repair"
        self._busy(True, cancellable=False)
        self.session.repair(self._on_progress, self._repaired)

    def _repaired(self, outcome):
        self._busy(False)
        self.phase = ""
        self._show_repair(outcome.broken)
        if not outcome.ok:
            self._failed(outcome)
            return
        _toast(self, tr("Repair completed"))
        self.check(refresh=False)

    def _checked(self, outcome, refreshed):
        self._busy(False)
        self.phase = ""
        self._show_repair(outcome.broken)
        self._render_updates(outcome.updates, outcome.held)
        n = len(outcome.updates)
        security = sum(1 for u in outcome.updates if u.security)
        if refreshed and outcome.ok:
            self.info["last_check"] = int(GLib.get_real_time() / 1e6)
            self.info["available"], self.info["security"] = n, security
            self.l_last_check.set_label(su.format_date(self.info["last_check"]))
        if not outcome.ok:
            if outcome.kind == su.CANCELLED:
                self._set_state(tr("Check cancelled"), self._known(n), "dialog-information-symbolic")
            else:
                self._set_state(self._title_for(outcome.kind), outcome.message +
                                ((" " + self._known(n)) if n else ""), "dialog-warning-symbolic")
                self._set_detail(outcome.detail)
            return
        if not refreshed:
            # from the lists already on disk: they can be old
            self.info["available"], self.info["security"] = n, security
        self._show_summary_state(n, security)

    def _known(self, n):
        if not n:
            return ""
        return ntr("The list from the last check shows {n} update.",
                   "The list from the last check shows {n} updates.", n).format(n=n)

    def _show_summary_state(self, n, security):
        # a pending restart has its own row with the button: the status row
        # tells the rest instead of repeating it
        self.r_restart.set_visible(bool(self.info.get("restart")))
        action = su.next_action_text(su.next_action(dict(self.info, restart=False)))
        if self.info.get("broken"):
            self._set_state(tr("The package system needs a repair"), action, "dialog-warning-symbolic")
        elif n:
            title = ntr("{n} update available", "{n} updates available", n).format(n=n)
            if security:
                title = ntr("{n} update available, {s} for security",
                            "{n} updates available, {s} for security", n).format(n=n, s=security)
            self._set_state(title, action, "software-update-available-symbolic")
        else:
            self._set_state(tr("ZETA RAYS is up to date"), action, "emblem-ok-symbolic")

    @staticmethod
    def _title_for(kind):
        return {
            su.NO_NETWORK: tr("No internet connection"),
            su.REPO_UNREACHABLE: tr("Software sources unreachable"),
            su.LOCKED: tr("Another program is installing software"),
            su.NOT_AUTHORIZED: tr("Not authorized"),
            su.UNAVAILABLE: tr("Update service not available"),
            su.BROKEN: tr("The package system needs a repair"),
        }.get(kind, tr("Could not check for updates"))

    def _render_updates(self, updates, held):
        for r in self.update_rows:
            self.g_updates.remove(r)
        self.update_rows = []
        previous = {pid for pid, c in self.checks.items() if not c.get_active()}
        self.checks = {}
        self.updates = list(updates)
        for u in self.updates:
            subtitle = "%s → %s" % (u.old_version or "?", u.version)
            if u.summary:
                subtitle += " · " + u.summary
            row = Adw.ActionRow(title=GLib.markup_escape_text(u.name),
                                subtitle=GLib.markup_escape_text(subtitle))
            row.set_subtitle_lines(2)
            check = Gtk.CheckButton(active=u.id not in previous, valign=Gtk.Align.CENTER,
                                    tooltip_text=tr("Include in the update"))
            check.connect("toggled", lambda *_: self._selection_changed())
            row.add_prefix(check)
            row.set_activatable_widget(check)
            if u.security:
                row.add_suffix(Gtk.Label(label=tr("Security"), valign=Gtk.Align.CENTER,
                                         css_classes=["caption-heading", "warning"]))
            if u.download_size:
                row.add_suffix(Gtk.Label(label=su.human_size(u.download_size),
                                         valign=Gtk.Align.CENTER, css_classes=["dim-label", "caption"]))
            self.checks[u.id] = check
            self.g_updates.add(row)
            self.update_rows.append(row)
        if held:
            self.r_held.set_subtitle(GLib.markup_escape_text(
                tr("Kept at the version tested with ZETA RAYS, updated with new releases: "
                   "{names}").format(names=", ".join(held))))
        self.r_held.set_visible(bool(held))
        self.g_updates.set_visible(bool(self.updates) or bool(held))
        self._selection_changed()

    def _selected(self):
        return [u for u in self.updates if self.checks.get(u.id) and self.checks[u.id].get_active()]

    def _selection_changed(self):
        chosen = self._selected()
        total = sum(u.download_size for u in chosen)
        if not self.updates:
            self.g_updates.set_description("")
        elif total:
            self.g_updates.set_description(ntr(
                "{n} selected, {size} to download", "{n} selected, {size} to download",
                len(chosen)).format(n=len(chosen), size=su.human_size(total)))
        else:
            self.g_updates.set_description(ntr("{n} selected", "{n} selected", len(chosen)).format(
                n=len(chosen)))
        self.b_install.set_label(tr("Update All") if len(chosen) == len(self.updates)
                                 else tr("Install Selected"))
        self.b_install.set_sensitive(bool(chosen) and not (self.session and self.session.busy))

    # ------------------------------------------------------------ install
    def install(self):
        chosen = self._selected()
        if not chosen or self.session is None or self.session.busy:
            return
        if su.is_live():
            self._confirm(tr("Install updates in the live session?"),
                          tr("You are using ZETA RAYS from the installation media: the updates "
                             "are lost when the computer restarts, and they use memory (RAM) "
                             "instead of disk space."),
                          tr("Install Anyway"), lambda: self._simulate(chosen))
            return
        self._simulate(chosen)

    def _simulate(self, chosen):
        self._set_detail("")
        self._set_state(tr("Preparing the update…"), tr("Checking dependencies and disk space."),
                        "emblem-synchronizing-symbolic")
        self.phase = "simulate"
        self._busy(True)
        self.session.simulate([u.id for u in chosen], self._on_progress,
                              lambda o: self._simulated(o, chosen))

    def _simulated(self, outcome, chosen):
        self._busy(False)
        self.phase = ""
        if not outcome.ok:
            self._failed(outcome)
            return
        problem = su.check_space(chosen, outcome.extra)
        if problem:
            self._set_state(tr("Not enough disk space"), problem, "dialog-warning-symbolic")
            return
        if outcome.removals:
            self._confirm(
                tr("Remove packages to update?"),
                ntr("To complete the update, this package must be removed: {names}.",
                    "To complete the update, these packages must be removed: {names}.",
                    len(outcome.removals)).format(names=", ".join(sorted(set(outcome.removals)))),
                tr("Remove and Update"), lambda: self._run(chosen, outcome.extra),
                destructive=True, on_cancel=lambda: self._show_summary_state(
                    len(self.updates), sum(1 for u in self.updates if u.security)))
            return
        self._run(chosen, outcome.extra)

    def _run(self, chosen, extra):
        self.download_total = sum(u.download_size for u in chosen) + sum(d for d, _s in extra)
        self._set_state(tr("Updating…"), tr("You can keep working. Do not turn off the computer "
                                            "while updates are installed."),
                        "emblem-synchronizing-symbolic")
        self.phase = "download"
        self._busy(True)
        self.session.install([u.id for u in chosen], self._on_progress,
                             lambda o: self._installed(o, len(chosen)), on_phase=self._on_phase)

    def _on_phase(self, phase):
        self.phase = phase
        self._fraction = None
        if phase == "install":
            self._set_state(tr("Installing updates…"),
                            tr("Do not turn off the computer until the installation is finished."),
                            "emblem-synchronizing-symbolic")

    def _installed(self, outcome, count):
        phase = self.phase
        self._busy(False)
        self.phase = ""
        if not outcome.ok:
            if outcome.kind == su.NO_NETWORK and phase == "download":
                outcome.message = tr("The download was interrupted: the internet connection was "
                                     "lost. Nothing was installed. Click “Update All” again when "
                                     "you are back online.")
            elif outcome.kind == su.CANCELLED:
                outcome.message = tr("Update cancelled. Nothing was installed.") if phase == "download" \
                    else tr("Update cancelled.")
            self._failed(outcome)
            return
        _toast(self, ntr("{n} update installed", "{n} updates installed", count).format(n=count))
        self.info["last_success"] = int(GLib.get_real_time() / 1e6)
        self.l_last_update.set_label(su.format_date(self.info["last_success"]))
        if outcome.restart == "system":
            self.info["restart"] = True
            self.r_restart.set_visible(True)
        elif outcome.restart == "session":
            _toast(self, tr("Log out and back in to finish the update."))
        # what is left (packages not selected, or new ones)
        self.check(refresh=False)

    def _failed(self, outcome):
        if outcome.kind == su.CANCELLED:
            self._set_state(tr("Cancelled"), outcome.message, "dialog-information-symbolic")
            return
        title = {su.NO_NETWORK: tr("No internet connection"),
                 su.REPO_UNREACHABLE: tr("Software sources unreachable"),
                 su.LOCKED: tr("Another program is installing software"),
                 su.NOT_AUTHORIZED: tr("Not authorized"),
                 su.UNAVAILABLE: tr("Update service not available"),
                 su.BROKEN: tr("The package system needs a repair"),
                 su.NO_SPACE: tr("Not enough disk space"),
                 su.CONFLICT: tr("The updates conflict with installed software"),
                 su.DOWNLOAD_FAILED: tr("Download interrupted"),
                 su.SIGNATURE: tr("Package not verified"),
                 su.INSTALL_FAILED: tr("An update could not be installed")}.get(
            outcome.kind, tr("The update did not complete"))
        self._set_state(title, outcome.message, "dialog-warning-symbolic")
        self._set_detail(outcome.detail)
        if outcome.kind in (su.BROKEN, su.INSTALL_FAILED):
            self._show_repair(su.broken_packages(), force=True)

    # ------------------------------------------------------------ dialogs and actions
    def _confirm(self, heading, body, ok_label, on_ok, destructive=False, on_cancel=None):
        dlg = Adw.AlertDialog(heading=heading, body=body)
        dlg.add_response("cancel", tr("Cancel"))
        dlg.add_response("ok", ok_label)
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive
                                    else Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("cancel" if destructive else "ok")
        dlg.set_close_response("cancel")

        def response(_d, resp):
            if resp == "ok":
                on_ok()
            elif on_cancel:
                on_cancel()
        dlg.connect("response", response)
        dlg.present(self.get_root())

    def ask_restart(self):
        self._confirm(tr("Restart now?"),
                      tr("Save your work first: open apps are closed."),
                      tr("Restart"), power.reboot)

    def on_auto(self, row, _p):
        if self._auto_guard:
            return
        on = row.get_active()
        row.set_sensitive(False)

        def done(result):
            ok, message = result
            row.set_sensitive(True)
            if not ok:
                # put the switch back where the system really is
                self._auto_guard = True
                row.set_active(not on)
                self._auto_guard = False
                _toast(self, message)
            else:
                _toast(self, tr("Automatic security updates on") if on
                       else tr("Automatic security updates off"))
            return False
        threading.Thread(target=lambda: GLib.idle_add(done, su.set_auto_updates(on)),
                         daemon=True).start()

    def on_reminder(self, row, _p):
        on = row.get_active()

        def work():
            return su.set_reminder(on)

        def done(ok):
            if not ok:
                _toast(self, tr("Could not change the reminder"))
            elif on:
                _toast(self, tr("Weekly reminder on"))
            return False
        threading.Thread(target=lambda: GLib.idle_add(done, work()), daemon=True).start()
