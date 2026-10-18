# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings > Language & Region.

Language, regional formats (dates, numbers, currency), keyboard layout and,
for Chinese, Japanese and Korean, the input method (Fcitx 5). Language and
keyboard are system settings, written by /usr/libexec/zeta-language through
pkexec; they apply everywhere (login screen, desktop, terminal, apps) after
logging out and back in. ZETA's own apps are translated into English and
Italian: with another language the system, Firefox, Thunderbird and the
GTK/Qt apps use it, and ZETA's apps stay in English rather than mixing.
"""
import gettext
import json
import os
import re
import subprocess
import threading

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import language as ui_language, tr  # noqa: E402
from system import applications as reg, power  # noqa: E402

LANGUAGES_FILE = "/usr/share/zeta/languages.json"
EVDEV = "/usr/share/X11/xkb/rules/evdev.lst"
ZETA_CATALOGS = "/usr/share/locale/%s/LC_MESSAGES/zetarays.mo"
HELPER = "/usr/libexec/zeta-language"
FILE_IM = os.path.expanduser("~/.config/zeta/input-method")
FCITX_PROFILE = os.path.expanduser("~/.config/fcitx5/profile")
IM_NAMES = {"mozc": "Mozc (日本語)", "pinyin": "Pinyin (简体中文)", "chewing": "Chewing / Zhuyin (繁體中文)",
           "hangul": "Hangul (한국어)"}


def languages():
    try:
        with open(LANGUAGES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return [{"locale": "en_US.UTF-8", "name": "English (United States)", "keyboard": "us", "im": ""}]


def read_kv(path):
    """KEY=value files of /etc/default (quotes removed)."""
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r'^\s*([A-Z_]+)=(.*)$', line)
                if m:
                    values[m.group(1)] = m.group(2).strip().strip('"\'')
    except OSError:
        pass
    return values


def _layout_name(code, description):
    """Gives "German (de)", but "English (US)" rather than "English (US)  (us)":
    the code is appended only when the name does not already include it."""
    if "(%s)" % code.lower() in description.lower():
        return description
    return "%s (%s)" % (description, code)


def layout_xkb():
    """[(code, description)] of every keyboard layout XKB knows, with the
    descriptions translated by xkeyboard-config itself."""
    out, section = [], ""
    try:
        with open(EVDEV, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("!"):
                    section = line[1:].strip()
                    continue
                if section == "layout" and line.strip():
                    code, _, desc = line.strip().partition(" ")
                    out.append((code, gettext.dgettext("xkeyboard-config", desc.strip())))
    except OSError:
        pass
    return sorted(out, key=lambda t: t[1].casefold()) or [("us", "English (US)")]


def zeta_translated(loc):
    base = loc.split(".")[0]
    if base.startswith("en"):
        return True
    return any(os.path.exists(ZETA_CATALOGS % x) for x in (base, base.split("_")[0]))


def preview(loc):
    """Date, time and number as they will look in these formats."""
    code = ("import locale, time\n"
              "locale.setlocale(locale.LC_ALL, '')\n"
              "print(time.strftime('%A %x  %X'), '·', locale.format_string('%.2f', 1234567.89, grouping=True))")
    try:
        r = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=5,
                           env=dict(os.environ, LC_ALL=loc))
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def write_fcitx_profile(keyboard, im):
    """Fcitx 5 starts with the keyboard and the chosen input method
    (Ctrl+Space switches between them)."""
    os.makedirs(os.path.dirname(FCITX_PROFILE), exist_ok=True)
    first = keyboard.split(",")[0] or "us"
    text = ("[Groups/0]\nName=Default\nDefault Layout=%s\nDefaultIM=%s\n\n"
             "[Groups/0/Items/0]\nName=keyboard-%s\nLayout=\n\n"
             "[Groups/0/Items/1]\nName=%s\nLayout=\n\n"
             "[GroupOrder]\n0=Default\n") % (first, im, first, im)
    with open(FCITX_PROFILE + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(FCITX_PROFILE + ".tmp", FCITX_PROFILE)


class LanguagePage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.languages = languages()
        current = read_kv("/etc/default/locale")
        self.current_locale = current.get("LANG", "en_US.UTF-8")
        self.current_fmt = current.get("LC_TIME", self.current_locale)
        keyboard_conf = read_kv("/etc/default/keyboard")
        self.current_keyboard = keyboard_conf.get("XKBLAYOUT", "us")

        # --- language
        g = Adw.PreferencesGroup(
            title=tr("Language"),
            description=tr("The language of the whole system: desktop, apps, terminal and messages "
                           "after you log out and back in; the login screen after a restart."))
        # Apply sits next to the first title: visible without scrolling
        self.apply = Gtk.Button(label=tr("Apply"), css_classes=["suggested-action"],
                                  valign=Gtk.Align.CENTER)
        self.apply.connect("clicked", lambda *_: self._apply())
        g.set_header_suffix(self.apply)
        self.language_row = Adw.ComboRow(title=tr("Language"),
                                   model=Gtk.StringList.new([l["name"] for l in self.languages]))
        self.language_row.set_selected(self._index(self.current_locale))
        self.language_row.connect("notify::selected", lambda *_: self._language_changed())
        g.add(self.language_row)
        self.note = Adw.ActionRow(title="", use_markup=False)
        self.note.add_css_class("dim-label")
        g.add(self.note)
        self.add(g)

        # --- formats
        gf = Adw.PreferencesGroup(title=tr("Formats"),
                                  description=tr("How dates, times, numbers and currency are written."))
        self.formats = Adw.ComboRow(title=tr("Region"), model=Gtk.StringList.new(
            [tr("Same as the language")] + [l["name"] for l in self.languages]))
        if self.current_fmt != self.current_locale:
            self.formats.set_selected(self._index(self.current_fmt) + 1)
        self.formats.connect("notify::selected", lambda *_: self._update_preview())
        gf.add(self.formats)
        self.example = Adw.ActionRow(title=tr("Example"), use_markup=False)
        self.example.add_css_class("property")
        gf.add(self.example)
        self.add(gf)

        # --- keyboard
        # Keyboards: a list, as on Windows and macOS (Italian, English US,
        # English UK...). Alt+Shift or the indicator in the bar switch
        # between them; the first one is the one used at login.
        self.gk = Adw.PreferencesGroup(
            title=tr("Keyboards"),
            description=tr("Add the keyboards you use. Alt+Shift, or a click on the indicator "
                           "in the bar, switches between them; the first one is the default."))
        self.layout = layout_xkb()
        self.keyboard_names = {c: _layout_name(c, d) for c, d in self.layout}
        self.chosen = [c for c in self.current_keyboard.split(",") if c in self.keyboard_names] or ["us"]
        self._keyboard_rows = []
        codes = [c for c, _d in self.layout]
        model = Gtk.StringList.new([self.keyboard_names[c] for c in codes])
        self.add_keyboard_row = Adw.ComboRow(
            title=tr("Add a keyboard"), model=model, enable_search=True,
            expression=Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        if "us" in codes:
            self.add_keyboard_row.set_selected(codes.index("us"))
        more = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER,
                         tooltip_text=tr("Add"))
        more.add_css_class("flat")
        more.connect("clicked", lambda *_: self._add_keyboard())
        self.add_keyboard_row.add_suffix(more)
        self._render_keyboards()
        self.add(self.gk)

        # --- input method
        gi_ = Adw.PreferencesGroup(
            title=tr("Input Method"),
            description=tr("To type Chinese, Japanese or Korean. Ctrl+Space switches between the "
                           "keyboard and the input method."))
        self.im_enabled = Adw.SwitchRow(title=tr("Use an input method"))
        self.im = Adw.ComboRow(title=tr("Input method"),
                               model=Gtk.StringList.new(list(IM_NAMES.values())))
        saved_im = self._saved_im()
        self.im_enabled.set_active(bool(saved_im))
        if saved_im in IM_NAMES:
            self.im.set_selected(list(IM_NAMES).index(saved_im))
        gi_.add(self.im_enabled)
        gi_.add(self.im)
        # Fcitx's own settings (more input methods, shortcuts); its entries
        # are hidden from the app menu, they belong here
        advanced = Adw.ActionRow(title=tr("Input method settings…"), activatable=True)
        advanced.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        advanced.connect("activated", lambda *_: reg.spawn(["fcitx5-config-qt"]))
        gi_.add(advanced)
        self.add(gi_)

        self._language_changed(initial=True)

    # ---- helpers
    def _index(self, loc):
        for i, l in enumerate(self.languages):
            if l["locale"] == loc:
                return i
        return 0

    def _saved_im(self):
        try:
            with open(FILE_IM, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    def _choice(self):
        l = self.languages[self.language_row.get_selected()]
        i = self.formats.get_selected()
        fmt = self.languages[i - 1]["locale"] if i > 0 else l["locale"]
        return l, fmt

    # ---- keyboards
    def _render_keyboards(self):
        for r in self._keyboard_rows + [self.add_keyboard_row]:
            if r.get_parent() is not None:
                self.gk.remove(r)
        self._keyboard_rows = []
        for i, code in enumerate(self.chosen):
            # markup off before the text: names may contain "&"
            line = Adw.ActionRow(use_markup=False)
            line.set_title(self.keyboard_names.get(code, code))
            line.set_subtitle(tr("Default") if i == 0 else "")
            if i > 0:
                su = Gtk.Button(icon_name="go-up-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text=tr("Move up"))
                su.add_css_class("flat")
                su.connect("clicked", lambda *_a, n=i: self._move_keyboard(n))
                line.add_suffix(su)
            if len(self.chosen) > 1:
                via = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER,
                                 tooltip_text=tr("Remove"))
                via.add_css_class("flat")
                via.connect("clicked", lambda *_a, c=code: self._remove_keyboard(c))
                line.add_suffix(via)
            self.gk.add(line)
            self._keyboard_rows.append(line)
        # at most four keyboards (the limit of the keyboard system, XKB)
        self.add_keyboard_row.set_sensitive(len(self.chosen) < 4)
        self.gk.add(self.add_keyboard_row)

    def _add_keyboard(self):
        code = self.layout[self.add_keyboard_row.get_selected()][0]
        if code not in self.chosen and len(self.chosen) < 4:
            self.chosen.append(code)
            self._render_keyboards()

    def _remove_keyboard(self, code):
        if len(self.chosen) > 1 and code in self.chosen:
            self.chosen.remove(code)
            self._render_keyboards()

    def _move_keyboard(self, n):
        self.chosen[n - 1], self.chosen[n] = self.chosen[n], self.chosen[n - 1]
        self._render_keyboards()

    def _apply_keyboard_now(self, keyboard):
        """The new keyboards in this session at once (no need to log out):
        Hyprland, the file it reads at login, and the indicator in the bar."""
        options = "grp:alt_shift_toggle" if "," in keyboard else ""
        variants = ",".join("" for _ in keyboard.split(","))
        try:
            folder = os.path.expanduser("~/.config/hypr")
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "zeta_keyboard.lua"), "w", encoding="utf-8") as f:
                f.write('return { layout = "%s", variant = "%s", options = "%s" }\n'
                        % (keyboard, variants, options))
        except OSError:
            pass
        reg.spawn(["hyprctl", "eval",
                    "hl.config({ input = { kb_layout = \"%s\", kb_variant = \"%s\", "
                    "kb_options = \"%s\" } })" % (keyboard, variants, options)])
        reg.spawn(["zeta-dock", "apply"])

    def _language_changed(self, initial=False):
        l, _fmt = self._choice()
        if zeta_translated(l["locale"]):
            self.note.set_title(tr("Everything is shown in this language."))
        else:
            self.note.set_title(tr("The system, Firefox, Thunderbird and most apps use this language; "
                                   "the ZETA RAYS apps are not translated into it yet and stay in English."))
        if not initial:
            # the usual keyboard and input method of the new language
            proposed = [c for c in l["keyboard"].split(",") if c in self.keyboard_names]
            if proposed:
                self.chosen = proposed
                self._render_keyboards()
            if l["im"]:
                self.im_enabled.set_active(True)
                self.im.set_selected(list(IM_NAMES).index(l["im"]))
        self._update_preview()

    def _update_preview(self):
        _l, fmt = self._choice()
        self.example.set_subtitle(preview(fmt) or fmt)

    def _toast(self, text, logout=False):
        w = self.get_root()
        toasts = getattr(w, "toasts", None)
        if toasts is None:
            return
        t = Adw.Toast(title=text, timeout=0 if logout else 4, use_markup=False)
        if logout:
            t.set_button_label(tr("Log Out"))
            t.connect("button-clicked", lambda *_: power.logout())
        toasts.add_toast(t)

    def _helper(self, *argv):
        r = subprocess.run(["pkexec", HELPER, "--lang=%s" % ui_language()] + list(argv),
                           capture_output=True, text=True)
        try:
            outcome = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            outcome = {}
        if r.returncode == 126:                  # password window closed by the user
            return None
        if r.returncode == 127 and not r.stdout.strip():
            return {"error": tr("The change needs an administrator's password, and it was not accepted.")}
        return outcome if r.returncode == 0 else {"error": outcome.get("error") or tr("Not changed.")}

    def _apply(self):
        l, fmt = self._choice()
        keyboard = ",".join(self.chosen)
        self.apply.set_sensitive(False)

        def work():
            outcomes = []
            language_changed = (l["locale"] != self.current_locale or fmt != self.current_fmt)
            if language_changed:
                outcomes.append(self._helper("language", l["locale"], *([fmt] if fmt != l["locale"] else [])))
            if keyboard != self.current_keyboard and (not outcomes or outcomes[-1] and "error" not in outcomes[-1]):
                outcomes.append(self._helper("keyboard", keyboard))
            GLib.idle_add(fine, outcomes, language_changed)

        def fine(outcomes, language_changed):
            self.apply.set_sensitive(True)
            self._save_im(keyboard)
            if any(e is None for e in outcomes):
                return False
            errors = [e["error"] for e in outcomes if "error" in e]
            if errors:
                self._toast(errors[0])
                return False
            if keyboard != self.current_keyboard:
                self._apply_keyboard_now(keyboard)
            self.current_locale, self.current_fmt, self.current_keyboard = l["locale"], fmt, keyboard
            if language_changed:
                self._toast(tr("Saved. Log out and back in to use the new settings everywhere."),
                            logout=True)
            elif outcomes:
                self._toast(tr("Saved. The keyboards are ready: Alt+Shift switches between them."))
            else:
                self._toast(tr("Saved."))
            return False

        threading.Thread(target=work, daemon=True).start()

    def _save_im(self, keyboard):
        """The input method is the user's own setting (no password)."""
        im = list(IM_NAMES)[self.im.get_selected()] if self.im_enabled.get_active() else ""
        if im == self._saved_im():
            return
        os.makedirs(os.path.dirname(FILE_IM), exist_ok=True)
        if im:
            with open(FILE_IM, "w", encoding="utf-8") as f:
                f.write(im + "\n")
            write_fcitx_profile(keyboard, im)
            reg.spawn(["fcitx5", "-d", "--replace"])
        else:
            try:
                os.unlink(FILE_IM)
            except OSError:
                pass
            subprocess.run(["pkill", "-x", "fcitx5"], capture_output=True)
