# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › Displays › Night Light.

On/off, schedule (always, sunset to sunrise, custom times) and color
temperature with a live preview while the slider moves. The work is done by
system/night_light.py (a single wlsunset process); every change runs in a
thread, one at a time, so the window never waits for it.
"""
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from system import night_light as nl  # noqa: E402

SCHEDULES = ("always", "sunset", "custom")
PREVIEW_MS = 200        # a new preview at most this often while dragging
BACK_MS = 2500          # then back to the saved schedule
_lock = threading.Lock()


def _job(work, done=None):
    """Run work() in a thread, one job at a time (wlsunset is replaced, never
    doubled), then done(result) in the UI thread."""
    def runner():
        with _lock:
            try:
                res = work()
            except (OSError, ValueError):
                res = None
        if done:
            GLib.idle_add(lambda: (done(res), False)[1])
    threading.Thread(target=runner, daemon=True).start()


class NightLightGroup(Adw.PreferencesGroup):
    def __init__(self):
        super().__init__(title=tr("Night Light"),
                         description=tr("Warmer colors make the screen easier on the eyes "
                                        "in the evening and at night."))
        self._updating = False
        self._preview_timer = None
        self._back_timer = None
        self._time_timer = None
        conf = nl.load()

        self.switch = Adw.SwitchRow(title=tr("Night Light"), active=conf["enabled"])
        self.switch.connect("notify::active", self._on_switch)
        self.add(self.switch)

        self.schedule = Adw.ComboRow(
            title=tr("Schedule"),
            model=Gtk.StringList.new([tr("Always on"), tr("Sunset to sunrise"),
                                      tr("Custom times")]))
        self.schedule.set_selected(SCHEDULES.index(conf["schedule"]))
        self.schedule.connect("notify::selected", self._on_schedule)
        self.add(self.schedule)

        self.sun_row = Adw.ActionRow(title=tr("Today"))
        self.sun_value = Gtk.Label(css_classes=["dim-label"])
        self.sun_row.add_suffix(self.sun_value)
        self.add(self.sun_row)

        self.from_row, self.from_h, self.from_m = self._time_row(tr("Turn on at"), conf["from"])
        self.to_row, self.to_h, self.to_m = self._time_row(tr("Turn off at"), conf["to"])
        self.add(self.from_row)
        self.add(self.to_row)

        temp_row = Adw.ActionRow(title=tr("Color temperature"),
                                 subtitle=tr("Lower is warmer"))
        self.temp = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 2500, 6000, 100)
        self.temp.set_value(conf["temperature"])
        self.temp.set_draw_value(False)
        self.temp.set_hexpand(True)
        self.temp.set_size_request(200, -1)
        self.temp.connect("value-changed", self._on_temperature)
        temp_row.add_suffix(self.temp)
        self.temp_label = Gtk.Label(label="%d K" % conf["temperature"], width_chars=7,
                                    xalign=1, css_classes=["dim-label", "numeric"])
        temp_row.add_suffix(self.temp_label)
        self.add(temp_row)

        self.unavailable = Adw.ActionRow(
            title=tr("Night light is not available"),
            subtitle=tr("The program that changes the screen colors is not installed."),
            visible=not nl.available())
        self.add(self.unavailable)
        self.connect("map", lambda *_: self.refresh())
        self._show_parts(conf)

    def _time_row(self, title, value):
        h, m = (int(x) for x in value.split(":"))
        row = Adw.ActionRow(title=title)
        box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        hours = Gtk.SpinButton.new_with_range(0, 23, 1)
        hours.set_value(h)
        hours.set_wrap(True)
        mins = Gtk.SpinButton.new_with_range(0, 59, 5)
        mins.set_value(m)
        mins.set_wrap(True)
        for spin in (hours, mins):
            spin.set_numeric(True)
            spin.set_width_chars(2)
            spin.connect("output", self._two_digits)
            spin.connect("value-changed", self._on_time)
        box.append(hours)
        box.append(Gtk.Label(label=":"))
        box.append(mins)
        row.add_suffix(box)
        return row, hours, mins

    @staticmethod
    def _two_digits(spin):
        spin.set_text("%02d" % spin.get_value_as_int())
        return True

    # ------------------------------------------------------------ state
    def _show_parts(self, conf):
        sched = conf["schedule"]
        self.from_row.set_visible(sched == "custom")
        self.to_row.set_visible(sched == "custom")
        self.sun_row.set_visible(sched == "sunset")

    def refresh(self):
        _job(nl.status, self._show_status)

    def _show_status(self, st):
        if not st:
            return
        self.unavailable.set_visible(not st["available"])
        if st["enabled"] and st["active"]:
            sub = (tr("On until {time}").format(time=st["night_to"])
                   if st["schedule"] != "always" and "night_to" in st else tr("On"))
        elif st["enabled"] and "night_from" in st:
            sub = tr("Turns on at {time}").format(time=st["night_from"])
        elif st["enabled"]:
            sub = tr("Off today: the sun does not set")
        else:
            sub = tr("Off")
        self.switch.set_subtitle(sub)
        if "night_from" in st:
            text = tr("{start} to {end}").format(start=st["night_from"], end=st["night_to"])
            self.sun_value.set_label(text)
            self.sun_row.set_subtitle("" if st["located"] else
                                      tr("The time zone gives no position: fixed times are used"))
        else:
            self.sun_value.set_label(tr("Always on") if st["active"] else tr("Off"))

    # ------------------------------------------------------------ changes
    def _save_and_apply(self, **values):
        def work():
            conf = nl.update(**values)
            nl.apply(conf)
            return nl.status(conf)
        _job(work, self._show_status)

    def _on_switch(self, row, _param):
        if not self._updating:
            self._save_and_apply(enabled=row.get_active())

    def _on_schedule(self, row, _param):
        if self._updating:
            return
        sched = SCHEDULES[row.get_selected()]
        conf = nl.load()
        conf["schedule"] = sched
        self._show_parts(conf)
        self._save_and_apply(schedule=sched)

    def _on_time(self, _spin):
        if self._updating:
            return
        if self._time_timer is not None:
            GLib.source_remove(self._time_timer)
        self._time_timer = GLib.timeout_add(600, self._time_changed)

    def _time_changed(self):
        self._time_timer = None
        start = "%02d:%02d" % (self.from_h.get_value_as_int(), self.from_m.get_value_as_int())
        end = "%02d:%02d" % (self.to_h.get_value_as_int(), self.to_m.get_value_as_int())
        if start != end:
            self._save_and_apply(**{"from": start, "to": end})
        return False

    def _on_temperature(self, scale):
        value = int(round(scale.get_value() / 100) * 100)
        self.temp_label.set_label("%d K" % value)
        if self._updating:
            return
        if self._preview_timer is None:
            self._preview_timer = GLib.timeout_add(PREVIEW_MS, self._preview)
        if self._back_timer is not None:
            GLib.source_remove(self._back_timer)
        self._back_timer = GLib.timeout_add(BACK_MS, self._back)

    def _preview(self):
        self._preview_timer = None
        value = int(round(self.temp.get_value() / 100) * 100)

        def work():
            nl.update(temperature=value)
            nl.preview(value)
        _job(work)
        return False

    def _back(self):
        self._back_timer = None
        _job(lambda: (nl.apply(), nl.status())[1], self._show_status)
        return False
