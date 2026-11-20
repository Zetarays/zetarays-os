# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings > Backup, in the spirit of Time Machine.

Two kinds of copies:

- Personal files: Déjà Dup (deja-dup), encrypted and incremental, to an
  external drive, a network folder or another disk. This page shows when
  the last backup was made, starts one, opens the restore window and turns
  the automatic backups on or off (org.gnome.DejaDup "periodic"; the
  monitor that runs them is started at login by zeta-session-services).
- System snapshots: Timeshift in rsync mode (the installed system is ext4),
  a copy of the system files that can bring the computer back to how it
  was. "Create Snapshot Now" and the automatic snapshot before each system
  update go through /usr/libexec/zeta-snapshot (pkexec, fixed arguments);
  the newest three automatic snapshots are kept.

On the live system there is nothing to back up yet: the page says so.
"""
import os
import shutil

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import ntr, tr  # noqa: E402
from system import snapshots  # noqa: E402
from ui.page_tools import bg, gsettings, spawn, toast  # noqa: E402

MONITOR = "/usr/libexec/deja-dup/deja-dup-monitor"


def _date_text(when):
    """A GLib.DateTime or datetime in the user's format, or "Never"."""
    if when is None:
        return tr("Never")
    if not isinstance(when, GLib.DateTime):
        when = GLib.DateTime.new_from_unix_local(int(when.timestamp()))
    return when.format("%x %X") or ""


class BackupPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.live = snapshots.is_live()
        self.dejadup = gsettings("org.gnome.DejaDup") if shutil.which("deja-dup") else None

        if self.live:
            g = Adw.PreferencesGroup()
            row = Adw.ActionRow(
                title=tr("Backups need ZETA RAYS installed on the computer"),
                subtitle=tr("You are using ZETA RAYS from the installation media: nothing here is "
                            "kept after a restart, so there is nothing to back up yet."))
            row.add_prefix(Gtk.Image(icon_name="dialog-information-symbolic"))
            g.add(row)
            self.add(g)

        # --- personal files (Déjà Dup)
        gp = Adw.PreferencesGroup(
            title=tr("Personal files"),
            description=tr("Your folders, encrypted, to an external drive, a network folder or "
                           "another disk. Only what changed is copied each time."))
        self.last = Adw.ActionRow(title=tr("Last backup"), subtitle="…")
        gp.add(self.last)
        self.auto = Adw.SwitchRow(title=tr("Back up automatically"),
                                  subtitle=tr("When a backup is due and the backup location is "
                                              "reachable"))
        gp.add(self.auto)
        now = Adw.ActionRow(title=tr("Back up now"))
        self.b_now = Gtk.Button(label=tr("Back Up Now"), valign=Gtk.Align.CENTER,
                                css_classes=["suggested-action"])
        self.b_now.connect("clicked", lambda *_: spawn("deja-dup", "--backup"))
        now.add_suffix(self.b_now)
        gp.add(now)
        restore = Adw.ActionRow(title=tr("Restore files"),
                                subtitle=tr("Bring back files or folders from a backup"),
                                activatable=True)
        restore.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        restore.connect("activated", lambda *_: spawn("deja-dup"))
        gp.add(restore)
        settings = Adw.ActionRow(title=tr("Backup settings"),
                                 subtitle=tr("Where to save, which folders, how long to keep"),
                                 activatable=True)
        settings.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        settings.connect("activated", lambda *_: spawn("deja-dup"))
        gp.add(settings)
        if self.dejadup is None:
            self.last.set_subtitle(tr("Not installed"))
            for r in (self.auto, now, restore, settings):
                r.set_sensitive(False)
        else:
            self.auto.set_active(self.dejadup.get_boolean("periodic"))
            self.auto.connect("notify::active", self._on_auto)
            self.dejadup.connect("changed", lambda *_: self._read_dejadup())
            self._read_dejadup()
            if self.live:
                for r in (self.auto, now):
                    r.set_sensitive(False)
        self.add(gp)

        # --- system snapshots (Timeshift)
        gs = Adw.PreferencesGroup(
            title=tr("System snapshots"),
            description=tr("A copy of the system files (not your personal folders): if an update "
                           "or a change breaks something, the computer can go back to how it was."))
        # the newest snapshots are listed inside this row
        self.snap_state = Adw.ExpanderRow(title=tr("Snapshots"), subtitle="…")
        gs.add(self.snap_state)
        self.before = Adw.SwitchRow(
            title=tr("Snapshot before each system update"),
            subtitle=tr("Software Update takes one first, if the disk has room. The newest three "
                        "are kept."),
            active=snapshots.before_update_enabled())
        self.before.connect("notify::active", self._on_before)
        gs.add(self.before)
        create = Adw.ActionRow(title=tr("Create a snapshot now"),
                               subtitle=tr("The first one takes a few minutes"))
        self.b_create = Gtk.Button(label=tr("Create Snapshot Now"), valign=Gtk.Align.CENTER)
        self.b_create.connect("clicked", lambda *_: self._create())
        create.add_suffix(self.b_create)
        gs.add(create)
        manage = Adw.ActionRow(title=tr("Open Timeshift"),
                               subtitle=tr("Restore a snapshot, delete old ones, schedule them"),
                               activatable=True)
        manage.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        manage.connect("activated", lambda *_: spawn("timeshift-launcher"))
        gs.add(manage)
        self.snapshot_rows = []
        if not snapshots.installed():
            self.snap_state.set_subtitle(tr("Not installed"))
            for r in (self.before, create, manage):
                r.set_sensitive(False)
        elif self.live:
            self.snap_state.set_subtitle(tr("Snapshots need ZETA RAYS installed on the computer."))
            for r in (self.before, create, manage):
                r.set_sensitive(False)
        self.add(gs)

        self.connect("map", lambda *_: self._refresh_snapshots())

    # ------------------------------------------------------------ Déjà Dup
    def _read_dejadup(self):
        text = self.dejadup.get_string("last-backup")
        when = GLib.DateTime.new_from_iso8601(text, None) if text else None
        self.last.set_subtitle(_date_text(when.to_local() if when else None))

    def _on_auto(self, row, _p):
        on = row.get_active()
        if on == self.dejadup.get_boolean("periodic"):
            return
        self.dejadup.set_boolean("periodic", on)
        if on and os.access(MONITOR, os.X_OK):
            # the monitor waits in the background and starts the backup when
            # it is due (at the next logins it is started by the session)
            spawn("/usr/libexec/zeta-session-services")

    # ------------------------------------------------------------ Timeshift
    def _refresh_snapshots(self):
        if not snapshots.installed() or self.live:
            return

        def done(found):
            if isinstance(found, Exception):
                found = []
            for r in self.snapshot_rows:
                self.snap_state.remove(r)
            self.snapshot_rows = []
            self.snap_state.set_enable_expansion(bool(found))
            if not found:
                self.snap_state.set_subtitle(tr("No snapshots yet"))
                return
            self.snap_state.set_subtitle(ntr("{n} snapshot, the newest from {date}",
                                             "{n} snapshots, the newest from {date}",
                                             len(found)).format(n=len(found),
                                                                date=_date_text(found[0]["time"])))
            for s in found[:5]:
                r = Adw.ActionRow(title=_date_text(s["time"]), use_markup=False,
                                  subtitle=tr("Automatic, before an update") if s["auto"]
                                  else tr("Created in Settings") if s["manual"]
                                  else (s["comment"] or tr("Created with Timeshift")))
                r.add_prefix(Gtk.Image(icon_name="document-open-recent-symbolic"))
                self.snap_state.add_row(r)
                self.snapshot_rows.append(r)
        bg(snapshots.listing, done)

    def _on_before(self, row, _p):
        try:
            snapshots.set_before_update(row.get_active())
        except OSError as e:
            toast(self, str(e))

    def _create(self):
        self.b_create.set_sensitive(False)
        self.snap_state.set_subtitle(tr("Creating a snapshot… you can keep working."))

        def done(res):
            self.b_create.set_sensitive(True)
            ok, message = res if isinstance(res, tuple) else (False, str(res))
            if message:
                toast(self, message)
            self._refresh_snapshots()
        bg(lambda: snapshots.create("manual"), done)
