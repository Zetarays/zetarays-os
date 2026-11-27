# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings › Users: every account of the computer.

Add a user (standard or administrator), change a name or a password, give
or take administrator rights, rename or remove an account, and see who is
logged in now. Changes go through /usr/libexec/zeta-users with pkexec (the
password typed here travels on its standard input, never on a command line).
zeta-users refuses what would lock everyone out (removing the last
administrator, deleting yourself) and never moves or removes a home folder
that holds protected data or another disk.

Every password field has the eye button that shows what was typed
(Adw.PasswordEntryRow), usable with the keyboard too.
"""
import json
import os
import pwd
import subprocess

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from ui.page_tools import bg, confirm, toast  # noqa: E402

HELPER = "/usr/libexec/zeta-users"
NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


def run_helper(args, password=None):
    """(ok, data) of one zeta-users command (pkexec unless it is list)."""
    cmd = ([HELPER] if args[0] == "list" else ["pkexec", HELPER]) + list(args)
    try:
        r = subprocess.run(cmd, input=(password + "\n") if password is not None else "",
                           capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        return False, {"error": str(e)}
    try:
        data = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, {"error": tr("Not changed (password not given?)")}
    return bool(data.get("ok")), data


def valid_name(name):
    return bool(name) and len(name) <= 32 and name[0].isalpha() and set(name) <= NAME_CHARS


class UsersPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.me = pwd.getpwuid(os.getuid()).pw_name
        self.group = Adw.PreferencesGroup(title=tr("Users"),
                                          description=tr("People who can log in to this computer."))
        add = Gtk.Button(label=tr("Add User…"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        add.connect("clicked", self._on_add)
        self.group.set_header_suffix(add)
        self.add(self.group)
        self.sess_group = Adw.PreferencesGroup(title=tr("Logged in now"))
        self.add(self.sess_group)
        self._rows = []
        self.refresh()

    # ------------------------------------------------------------ listing
    def refresh(self):
        bg(lambda: run_helper(["list"]), self._fill)

    def _fill(self, res):
        ok, data = res if isinstance(res, tuple) else (False, {})
        for group, row in self._rows:
            group.remove(row)
        self._rows = []
        users = data.get("users", []) if ok else []
        admins = [u for u in users if u["admin"]]
        for u in users:
            row = Adw.ExpanderRow(title=GLib.markup_escape_text(u["full_name"] or u["name"]))
            badges = [u["name"], tr("Administrator") if u["admin"] else tr("Standard")]
            if u["name"] == self.me:
                badges.append(tr("you"))
            if u["logged_in"]:
                badges.append(tr("logged in"))
            row.set_subtitle(GLib.markup_escape_text(" · ".join(badges)))

            full = Adw.EntryRow(title=tr("Full name"), text=u["full_name"], show_apply_button=True)
            full.connect("apply", lambda r, n=u["name"]: self._do(["fullname", n, r.get_text().strip()],
                                                                   tr("Name changed")))
            row.add_row(full)

            pw = Adw.ActionRow(title=tr("Password"))
            b = Gtk.Button(label=tr("Change…"), valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda *_, n=u["name"]: self._password_dialog(n))
            pw.add_suffix(b)
            row.add_row(pw)

            adm = Adw.SwitchRow(title=tr("Administrator"),
                                subtitle=tr("Can install software, change system settings and manage users"),
                                active=u["admin"])
            if u["admin"] and len(admins) == 1:
                adm.set_sensitive(False)
                adm.set_subtitle(tr("The only administrator: give another user administrator rights first"))
            adm.connect("notify::active", self._on_admin, u["name"])
            row.add_row(adm)

            if u["name"] != self.me:
                ren = Adw.ActionRow(title=tr("User name"), subtitle=u["name"])
                b = Gtk.Button(label=tr("Rename…"), valign=Gtk.Align.CENTER, sensitive=not u["logged_in"])
                if u["logged_in"]:
                    ren.set_subtitle(tr("{name} · log this user out to rename").format(name=u["name"]))
                b.connect("clicked", lambda *_, n=u["name"]: self._rename_dialog(n))
                ren.add_suffix(b)
                row.add_row(ren)
                rm = Adw.ActionRow(title=tr("Remove this account"))
                b = Gtk.Button(label=tr("Remove…"), valign=Gtk.Align.CENTER, css_classes=["destructive-action"],
                               sensitive=not u["logged_in"] and not (u["admin"] and len(admins) == 1))
                b.connect("clicked", lambda *_, n=u["name"]: self._remove_dialog(n))
                rm.add_suffix(b)
                row.add_row(rm)
            self.group.add(row)
            self._rows.append((self.group, row))
        if not ok:
            row = Adw.ActionRow(title=tr("The list of users could not be read."))
            self.group.add(row)
            self._rows.append((self.group, row))
        for s in data.get("sessions", []) if ok else []:
            where = tr("remote (SSH)") if s["remote"] else (s["seat"] or s["tty"] or "?")
            row = Adw.ActionRow(title=s["user"], subtitle="%s · %s" % (where, s["state"]))
            self.sess_group.add(row)
            self._rows.append((self.sess_group, row))

    # ------------------------------------------------------------ actions
    def _do(self, args, done_text, password=None):
        def done(res):
            ok, data = res
            if ok:
                note, kept = data.get("home_kept_because"), data.get("home_kept_as")
                if note:
                    toast(self, tr("{done}. The home folder was left in place: it contains {path}").format(
                        done=done_text, path=note))
                elif kept:
                    toast(self, tr("{done}. The files are kept in {path}, readable only by administrators").format(
                        done=done_text, path=kept))
                else:
                    toast(self, done_text)
            else:
                toast(self, data.get("error") or tr("Not changed"))
            self.refresh()
        bg(lambda: run_helper(args, password), done)

    def _on_admin(self, row, _p, name):
        on = row.get_active()
        if on:
            self._do(["admin", name, "on"], tr("Administrator rights given"))
        else:
            self._do(["admin", name, "off"], tr("Administrator rights removed"))

    def _dialog(self, heading, body, ok_label, destructive=False):
        d = Adw.AlertDialog(heading=heading, body=body)
        d.add_response("cancel", tr("Cancel"))
        d.add_response("ok", ok_label)
        d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive
                                  else Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("ok")
        d.set_close_response("cancel")
        box = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        d.set_extra_child(box)
        return d, box

    def _password_rows(self, box):
        p1 = Adw.PasswordEntryRow(title=tr("New password"))
        p2 = Adw.PasswordEntryRow(title=tr("Repeat the password"))
        box.append(p1)
        box.append(p2)
        return p1, p2

    def _password_dialog(self, name):
        d, box = self._dialog(tr("New password for {name}").format(name=name),
                              tr("The eye button shows what you typed."), tr("Change"))
        p1, p2 = self._password_rows(box)

        def chosen(_d, resp):
            if resp != "ok":
                return
            if not p1.get_text() or p1.get_text() != p2.get_text():
                toast(self, tr("The two passwords are different (or empty)"))
                return
            self._do(["passwd", name], tr("Password changed"), password=p1.get_text())
        d.connect("response", chosen)
        d.present(self.get_root())

    def _on_add(self, *_a):
        d, box = self._dialog(tr("Add a user"), tr("The new person logs in with this user name and password."),
                              tr("Add"))
        full = Adw.EntryRow(title=tr("Full name"))
        user = Adw.EntryRow(title=tr("User name (lowercase, no spaces)"))
        box.append(full)
        box.append(user)

        last = {"suggested": ""}

        def suggest(*_a):
            # the user name follows the first name until it is edited by hand
            if user.get_text() not in ("", last["suggested"]):
                return
            words = full.get_text().lower().split()
            base = "".join(c for c in (words[0] if words else "") if c in NAME_CHARS)
            last["suggested"] = base
            user.set_text(base)
        full.connect("notify::text", suggest)
        p1, p2 = self._password_rows(box)
        adm = Adw.SwitchRow(title=tr("Administrator"))
        box.append(adm)

        def chosen(_d, resp):
            if resp != "ok":
                return
            name = user.get_text().strip()
            if not valid_name(name):
                toast(self, tr("User name: lowercase letters, digits, - and _, starting with a letter"))
                return
            if not p1.get_text() or p1.get_text() != p2.get_text():
                toast(self, tr("The two passwords are different (or empty)"))
                return
            self._do(["add", name, full.get_text().strip(), "admin" if adm.get_active() else "standard"],
                     tr("User added"), password=p1.get_text())
        d.connect("response", chosen)
        d.present(self.get_root())

    def _rename_dialog(self, name):
        d, box = self._dialog(tr("Rename {name}").format(name=name),
                              tr("The login name changes; the home folder follows it when possible."), tr("Rename"))
        new = Adw.EntryRow(title=tr("New user name"))
        box.append(new)

        def chosen(_d, resp):
            if resp != "ok":
                return
            n = new.get_text().strip()
            if not valid_name(n):
                toast(self, tr("User name: lowercase letters, digits, - and _, starting with a letter"))
                return
            self._do(["rename", name, n], tr("User renamed"))
        d.connect("response", chosen)
        d.present(self.get_root())

    def _remove_dialog(self, name):
        d, box = self._dialog(tr("Remove {name}?").format(name=name),
                              tr("The account is removed. Choose what happens to its files."), tr("Remove"),
                              destructive=True)
        keep = Adw.SwitchRow(title=tr("Keep the home folder"),
                             subtitle=tr("Off: the files of this user are deleted for good"), active=True)
        box.append(keep)

        def chosen(_d, resp):
            if resp != "ok":
                return
            if keep.get_active():
                self._do(["delete", name, "keep"], tr("User removed, files kept"))
                return
            confirm(self, tr("Delete the files of {name}?").format(name=name),
                    tr("Every file in the home folder of this user is deleted for good."),
                    tr("Delete"), lambda: self._do(["delete", name, "remove"], tr("User and files removed")),
                    destructive=True)
        d.connect("response", chosen)
        d.present(self.get_root())
