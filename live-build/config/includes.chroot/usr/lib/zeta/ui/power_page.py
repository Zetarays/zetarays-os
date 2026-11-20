# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › Power & Battery.

  Power mode     Power Saver / Balanced / Performance (power-profiles-daemon;
                 only the modes this computer offers)
  Battery        charge, time left, health, cycles (only with a battery)
  Screen & sleep turn off the screen, lock, suspend after some idle minutes
                 (zeta-appearance keys screen-off, auto-lock, auto-suspend:
                 it writes ~/.config/hypr/hypridle.conf and restarts hypridle)
  Power button   what the button does (logind, through the polkit helper
                 /usr/libexec/zeta-power-button)

Everything is read in a thread when the page is shown; nothing runs while
it is hidden.
"""
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import ntr, tr  # noqa: E402
from system import power, run  # noqa: E402
from ui.settings_pages import bg, toast  # noqa: E402

IDLE_CHOICES = (0, 1, 2, 3, 5, 10, 15, 20, 30, 45, 60, 90, 120)
SUSPEND_CHOICES = (0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240)
APPEARANCE_DIR = os.path.expanduser("~/.config/zeta")
IDLE_DEFAULTS = {"screen-off": 10, "auto-lock": 10, "auto-suspend": 0}
LIVE = os.path.isdir("/run/live/medium")


def duration_label(n):
    if n == 0:
        return tr("Never")
    if n >= 60 and n % 60 == 0:
        return ntr("{n} hour", "{n} hours", n // 60).format(n=n // 60)
    return ntr("{n} minute", "{n} minutes", n).format(n=n)


def time_left_label(minutes):
    h, m = divmod(int(minutes), 60)
    if h:
        return tr("{h} h {m} min").format(h=h, m=m)
    return tr("{m} min").format(m=m)


def read_idle(key):
    """The value zeta-appearance keeps in ~/.config/zeta/<key>."""
    try:
        with open(os.path.join(APPEARANCE_DIR, key)) as f:
            v = f.read().strip()
        return int(v) if v.isdigit() else IDLE_DEFAULTS[key]
    except OSError:
        return IDLE_DEFAULTS[key]


def profile_texts():
    return {
        "power-saver": (tr("Power Saver"),
                        tr("Less heat and fan noise, longer battery life, lower performance")),
        "balanced": (tr("Balanced"), tr("Good performance with reasonable power use")),
        "performance": (tr("Performance"),
                        tr("Highest performance, more heat, fan noise and power use")),
    }


def button_texts():
    return {"poweroff": tr("Shut down"), "suspend": tr("Suspend"),
            "lock": tr("Lock the screen"), "ignore": tr("Do nothing")}


class PowerPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__(title=tr("Power & Battery"), icon_name="zeta-power")
        self._updating = False
        self._timer = None
        self._loading = False

        # --- power mode ---
        self.mode_group = Adw.PreferencesGroup(
            title=tr("Power Mode"),
            description=tr("Balance performance against battery life, heat and fan noise."),
            visible=False)
        self.mode_rows = {}
        first = None
        for key, (title, subtitle) in profile_texts().items():
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if first is None:
                first = check
            else:
                check.set_group(first)
            check.connect("toggled", self._on_mode, key)
            row = Adw.ActionRow(title=title, subtitle=subtitle, activatable_widget=check)
            row.add_prefix(check)
            row.check = check
            self.mode_rows[key] = row
            self.mode_group.add(row)
        self.degraded = Adw.ActionRow(title=tr("Performance is limited right now"),
                                      visible=False)
        self.mode_group.add(self.degraded)
        self.add(self.mode_group)

        # --- battery ---
        self.bat_group = Adw.PreferencesGroup(title=tr("Battery"), visible=False)
        self.r_charge = Adw.ActionRow(title=tr("Charge"))
        self.r_left = Adw.ActionRow(title=tr("Time left"))
        self.r_health = Adw.ActionRow(
            title=tr("Battery health"),
            subtitle=tr("Capacity compared with a new battery"))
        self.r_cycles = Adw.ActionRow(title=tr("Charge cycles"))
        self.r_model = Adw.ActionRow(title=tr("Model"))
        self.bat_values = {}
        for row in (self.r_charge, self.r_left, self.r_health, self.r_cycles, self.r_model):
            value = Gtk.Label(css_classes=["dim-label"], selectable=True)
            row.add_suffix(value)
            self.bat_values[row] = value
            self.bat_group.add(row)
        self.add(self.bat_group)

        # --- screen and sleep ---
        self.idle_group = Adw.PreferencesGroup(
            title=tr("Screen and Sleep"),
            description=(tr("On the live system the screen never turns off, locks or "
                            "sleeps by itself: these settings apply after installation.")
                         if LIVE else
                         tr("What happens when you don't use the computer for a while.")))
        self.idle_rows = {}
        for key, title, choices in (
                ("screen-off", tr("Turn off the screen after"), IDLE_CHOICES),
                ("auto-lock", tr("Lock the screen after"), IDLE_CHOICES),
                ("auto-suspend", tr("Suspend after"), SUSPEND_CHOICES)):
            row = Adw.ComboRow(title=title)
            row.key = key
            row.values = list(choices)
            row.connect("notify::selected", self._on_idle)
            self.idle_rows[key] = row
            self.idle_group.add(row)
        self.add(self.idle_group)

        # --- power button ---
        self.button_group = Adw.PreferencesGroup(
            title=tr("Power Button"),
            description=tr("Changing it asks for the administrator password."),
            visible=False)
        self.button_row = Adw.ComboRow(title=tr("When the power button is pressed"))
        self.button_row.values = []
        self.button_row.current = None
        self.button_row.pending = False
        self.button_row.connect("notify::selected", self._on_button)
        self.button_group.add(self.button_row)
        self.add(self.button_group)

        self.connect("map", lambda *_: self._shown())
        self.connect("unmap", lambda *_: self._hidden())

    # ------------------------------------------------------------ reading
    def _shown(self):
        self.refresh()
        if self._timer is None:
            # battery and power mode can change while the page is open
            self._timer = GLib.timeout_add_seconds(30, self._tick)

    def _hidden(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self):
        self.refresh()
        return True

    def refresh(self):
        if self._loading:
            return
        self._loading = True

        def work():
            return {"profiles": power.power_profiles(),
                    "battery": power.battery_details(),
                    "button": power.power_button_action(),
                    "can_suspend": power.can_suspend(),
                    "helper": os.access(power.POWER_BUTTON_HELPER, os.X_OK),
                    "idle": {k: read_idle(k) for k in IDLE_DEFAULTS}}
        bg(work, self._show)

    def _show(self, d):
        self._loading = False
        self._updating = True
        try:
            self._show_modes(d["profiles"])
            self._show_battery(d["battery"])
            self._show_idle(d["idle"], d["can_suspend"])
            self._show_button(d["button"], d["can_suspend"], d["helper"])
        finally:
            self._updating = False

    def _show_modes(self, p):
        self.mode_group.set_visible(bool(p and p["available"]))
        if not p:
            return
        for key, row in self.mode_rows.items():
            row.set_visible(key in p["available"])
            if key == p["active"]:
                row.check.set_active(True)
        reason = {"lap-detected": tr("The computer is on your lap"),
                  "high-operating-temperature": tr("The computer is too hot")}.get(
                      p["degraded"], p["degraded"])
        self.degraded.set_subtitle(reason)
        self.degraded.set_visible(bool(p["degraded"]))

    def _show_battery(self, b):
        self.bat_group.set_visible(b is not None)
        if not b:
            return

        def put(row, text):
            row.set_visible(bool(text))
            self.bat_values[row].set_label(text or "")
        pct = "%d%%" % b["percent"] if b["percent"] is not None else ""
        put(self.r_charge, " · ".join(x for x in (pct, b["state"]) if x))
        if b["minutes"] is not None:
            self.r_left.set_title(tr("Time to full") if b["status"] == "Charging"
                                  else tr("Time left"))
            put(self.r_left, time_left_label(b["minutes"]))
        else:
            put(self.r_left, "")
        put(self.r_health, "%d%%" % b["health"] if b["health"] else "")
        put(self.r_cycles, str(b["cycles"]) if b["cycles"] else "")
        put(self.r_model, b["model"])

    @staticmethod
    def _fill_combo(row, values, labels, selected):
        """New list only when it changed: an open drop-down is not reset by
        the periodic refresh."""
        if getattr(row, "labels", None) != labels:
            row.labels = labels
            row.set_model(Gtk.StringList.new(labels))
        row.values = values
        if row.get_selected() != selected:
            row.set_selected(selected)

    def _show_idle(self, values, can_suspend):
        for key, row in self.idle_rows.items():
            v = values[key]
            choices = sorted(set(row.values) | {v})
            self._fill_combo(row, choices, [duration_label(n) for n in choices],
                             choices.index(v))
        # suspend: not offered where it cannot work (virtual machines)
        self.idle_rows["auto-suspend"].set_visible(can_suspend or values["auto-suspend"] > 0)

    def _show_button(self, current, can_suspend, helper):
        self.button_group.set_visible(helper)
        if self.button_row.pending:
            return                       # the password dialog is still open
        names = button_texts()
        values = [v for v in power.POWER_BUTTON_ACTIONS if v != "suspend" or can_suspend]
        labels = [names[v] for v in values]
        if current not in values:
            values.append(current)
            labels.append(names.get(current, current))
        self.button_row.current = current
        self._fill_combo(self.button_row, values, labels, values.index(current))

    # ------------------------------------------------------------ changes
    def _on_mode(self, check, key):
        if self._updating or not check.get_active():
            return

        def done(ok):
            if not ok:
                toast(self, tr("Couldn't change the power mode"))
            self.refresh()
        bg(lambda: power.set_power_profile(key), done)

    def _on_idle(self, row, _param):
        if self._updating:
            return
        value = row.values[row.get_selected()]
        bg(lambda: run(["zeta-appearance", "set", row.key, str(value)], timeout=20, check=True)
           is not None,
           lambda ok: None if ok else toast(self, tr("Couldn't save the setting")))

    def _on_button(self, row, _param):
        if self._updating:
            return
        value = row.values[row.get_selected()]
        if value == row.current:
            return

        def done(ok):
            row.pending = False
            if ok:
                row.current = value
                toast(self, tr("Power button: {action}").format(
                    action=button_texts().get(value, value)))
            else:
                self._updating = True
                row.set_selected(row.values.index(row.current))
                self._updating = False
                toast(self, tr("The power button setting was not changed"))
        row.pending = True
        bg(lambda: power.set_power_button_action(value), done)
