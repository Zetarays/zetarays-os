# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings > Date & Time.

Automatic time (NTP, systemd-timesyncd), the time zone and, when the
automatic time is off, the date and time set by hand. All three go through
systemd-timedated over D-Bus: it asks PolicyKit itself, so the session's
password window appears only when the change needs it. No helper of ours
runs as root.

The bar clock follows two personal choices kept in ~/.config/zeta
(clock-24h, clock-date) and read by system/dock.py.
"""
import datetime
import os
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from ui.page_tools import bg, spawn, toast  # noqa: E402

BUS = "org.freedesktop.timedate1"
OBJ = "/org/freedesktop/timedate1"
CFG = os.path.expanduser("~/.config/zeta")
ZONE_TABLES = ("/usr/share/zoneinfo/tzdata.zi",)


def clock_pref(name):
    """clock-24h / clock-date: on unless turned off ("0")."""
    try:
        with open(os.path.join(CFG, name), encoding="utf-8") as f:
            return f.read().strip() != "0"
    except OSError:
        return True


def set_clock_pref(name, on):
    os.makedirs(CFG, exist_ok=True)
    with open(os.path.join(CFG, name), "w", encoding="utf-8") as f:
        f.write("1\n" if on else "0\n")


def zones_from_files():
    """Time zone names without D-Bus (tzdata's compact table)."""
    names = set()
    for path in ZONE_TABLES:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] == "Z":
                        names.add(parts[1])
                    elif len(parts) >= 3 and parts[0] == "L":
                        names.add(parts[2])
        except OSError:
            pass
    return sorted(n for n in names if "/" in n and not n.startswith(("Etc/", "SystemV/"))) + ["UTC"]


def zone_label(name):
    """"Europe/Rome" -> "Europe / Rome (UTC+01:00)"."""
    offset = ""
    try:
        from zoneinfo import ZoneInfo
        delta = datetime.datetime.now(ZoneInfo(name)).utcoffset()
        minutes = int(delta.total_seconds() // 60)
        offset = " (UTC%s%02d:%02d)" % ("+" if minutes >= 0 else "-", abs(minutes) // 60, abs(minutes) % 60)
    except Exception:  # noqa: BLE001 - a zone tzdata cannot read keeps its bare name
        pass
    return name.replace("_", " ").replace("/", " / ") + offset


class DateTimePage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.proxy = None
        self.zones = []
        self._guard = False
        self._tick_id = None

        g = Adw.PreferencesGroup(title=tr("Date and time"))
        self.now_row = Adw.ActionRow(title=tr("Now"), subtitle="…")
        self.now_row.add_css_class("property")
        g.add(self.now_row)
        self.ntp = Adw.SwitchRow(title=tr("Set the time automatically"),
                                 subtitle=tr("From the internet time servers, when online"))
        self.ntp.set_sensitive(False)
        self.ntp.connect("notify::active", self._on_ntp)
        g.add(self.ntp)
        self.manual = Adw.ActionRow(title=tr("Date and time"),
                                    subtitle=tr("Set by hand when the automatic time is off"))
        self.manual_button = Gtk.MenuButton(label=tr("Change…"), valign=Gtk.Align.CENTER,
                                            popover=self._manual_popover())
        self.manual.add_suffix(self.manual_button)
        self.manual.set_sensitive(False)
        g.add(self.manual)
        self.add(g)

        gz = Adw.PreferencesGroup(title=tr("Time zone"),
                                  description=tr("Type to search for a city or a region."))
        self.zone = Adw.ComboRow(title=tr("Time zone"), enable_search=True,
                                 expression=Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self.zone.set_model(Gtk.StringList.new([tr("Loading…")]))
        self.zone.set_sensitive(False)
        self.zone.connect("notify::selected", self._on_zone)
        gz.add(self.zone)
        self.add(gz)

        gc = Adw.PreferencesGroup(title=tr("Clock in the bar"))
        self.h24 = Adw.SwitchRow(title=tr("24-hour clock"), subtitle=tr("15:30 instead of 3:30 PM"),
                                 active=clock_pref("clock-24h"))
        self.h24.connect("notify::active", lambda r, _p: self._clock("clock-24h", r.get_active()))
        gc.add(self.h24)
        self.show_date = Adw.SwitchRow(title=tr("Show the date"),
                                       subtitle=tr("Below the time"), active=clock_pref("clock-date"))
        self.show_date.connect("notify::active", lambda r, _p: self._clock("clock-date", r.get_active()))
        gc.add(self.show_date)
        self.add(gc)

        self.connect("map", lambda *_: self._start_clock())
        self.connect("unmap", lambda *_: self._stop_clock())
        Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None, BUS, OBJ,
                                  "org.freedesktop.timedate1", None, self._proxy_ready)

    # ------------------------------------------------------------ clock line
    def _start_clock(self):
        self._tick()
        if self._tick_id is None:
            self._tick_id = GLib.timeout_add_seconds(1, self._tick)

    def _stop_clock(self):
        if self._tick_id is not None:
            GLib.source_remove(self._tick_id)
            self._tick_id = None

    def _tick(self):
        # the C library (not GLib, which keeps the zone it read first) so a new
        # time zone shows at once after time.tzset()
        fmt = "%x  %H:%M:%S" if self.h24.get_active() else "%x  %I:%M:%S %p"
        self.now_row.set_subtitle(time.strftime(fmt))
        return True

    # ------------------------------------------------------------ timedated
    def _proxy_ready(self, _source, result):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error as e:
            print("zeta-settings: timedated: %s" % e.message)
            return
        self.proxy.connect("g-properties-changed", lambda *_: self._read_properties())
        self._read_properties()
        self.proxy.call("ListTimezones", None, Gio.DBusCallFlags.NONE, 10000, None, self._zones_listed)

    def _prop(self, name, default=None):
        v = self.proxy.get_cached_property(name) if self.proxy else None
        return v.unpack() if v is not None else default

    def _read_properties(self):
        self._guard = True
        can = bool(self._prop("CanNTP", False))
        on = bool(self._prop("NTP", False))
        self.ntp.set_sensitive(can)
        self.ntp.set_active(on)
        if not can:
            self.ntp.set_subtitle(tr("Not available on this system"))
        elif on and self._prop("NTPSynchronized") is False:
            self.ntp.set_subtitle(tr("Waiting for the time servers…"))
        else:
            self.ntp.set_subtitle(tr("From the internet time servers, when online"))
        self.manual.set_sensitive(not on)
        current = self._prop("Timezone", "")
        if current in self.zones:
            self.zone.set_selected(self.zones.index(current))
        self._guard = False

    def _zones_listed(self, proxy, result):
        try:
            names = list(proxy.call_finish(result).unpack()[0])
        except GLib.Error:
            names = []
        names = names or zones_from_files()

        def labels():
            return [zone_label(n) for n in names]

        def done(texts):
            if isinstance(texts, Exception):
                texts = list(names)
            self._guard = True
            self.zones = names
            self.zone.set_model(Gtk.StringList.new(texts))
            current = self._prop("Timezone", "")
            if current in names:
                self.zone.set_selected(names.index(current))
            self.zone.set_sensitive(True)
            self._guard = False
        bg(labels, done)          # several hundred zones: offsets computed off the UI thread

    def _call(self, method, args, what, then=None):
        """A timedated call; the password window comes from PolicyKit."""
        def finished(proxy, result):
            try:
                proxy.call_finish(result)
                ok = True
            except GLib.Error as e:
                ok = False
                if "Cancelled" not in e.message and "dismissed" not in e.message.lower():
                    print("zeta-settings: %s: %s" % (method, e.message))
                    toast(self, tr("Could not change {what}.").format(what=what))
            self._read_properties()
            if then:
                then(ok)
        self.proxy.call(method, args, Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 120000,
                        None, finished)

    def _on_ntp(self, row, _p):
        if self._guard or self.proxy is None:
            return
        self._call("SetNTP", GLib.Variant("(bb)", (row.get_active(), True)), tr("the automatic time"))

    def _on_zone(self, row, _p):
        if self._guard or self.proxy is None or not self.zones:
            return
        i = row.get_selected()
        if not 0 <= i < len(self.zones) or self.zones[i] == self._prop("Timezone", ""):
            return

        def then(ok):
            if ok:
                time.tzset()
                self._tick()
                # the bar clock reads the zone when it starts: reload it
                spawn("zeta-dock", "apply")
                toast(self, tr("Time zone changed"))
        self._call("SetTimezone", GLib.Variant("(sb)", (self.zones[i], True)), tr("the time zone"), then)

    # ------------------------------------------------------------ manual time
    def _manual_popover(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=10,
                      margin_bottom=10, margin_start=10, margin_end=10)
        self.calendar = Gtk.Calendar()
        box.append(self.calendar)
        line = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.hour = Gtk.SpinButton.new_with_range(0, 23, 1)
        self.minute = Gtk.SpinButton.new_with_range(0, 59, 1)
        for s in (self.hour, self.minute):
            s.set_wrap(True)
            s.set_numeric(True)
            s.set_width_chars(2)
        line.append(self.hour)
        line.append(Gtk.Label(label=":"))
        line.append(self.minute)
        box.append(line)
        apply = Gtk.Button(label=tr("Set"), css_classes=["suggested-action"])
        apply.connect("clicked", lambda *_: self._set_manual())
        box.append(apply)
        pop = Gtk.Popover(child=box)
        pop.connect("show", lambda *_: self._fill_manual())
        return pop

    def _fill_manual(self):
        now = GLib.DateTime.new_now_local()
        self.calendar.select_day(now)
        self.hour.set_value(now.get_hour())
        self.minute.set_value(now.get_minute())

    def _set_manual(self):
        self.manual_button.popdown()
        if self.proxy is None:
            return
        day = self.calendar.get_date()
        when = GLib.DateTime.new_local(day.get_year(), day.get_month(), day.get_day_of_month(),
                                       int(self.hour.get_value()), int(self.minute.get_value()), 0)
        if when is None:
            return
        usec = when.to_unix() * 1000000
        self._call("SetTime", GLib.Variant("(xbb)", (usec, False, True)), tr("the date and time"),
                   lambda ok: (self._tick(), toast(self, tr("Date and time changed")) if ok else None))

    # ------------------------------------------------------------ bar clock
    def _clock(self, name, on):
        try:
            set_clock_pref(name, on)
        except OSError:
            return
        self._tick()
        spawn("zeta-dock", "apply")
