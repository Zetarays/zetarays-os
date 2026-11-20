# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS: clipboard history (Super+V), a view of zeta-clipboard.

Text and images copied recently, newest first. Click or Enter: the entry
goes back to the clipboard and is pasted into the window that had the focus.
Delete removes the selected entry, "Clear all" empties the history, the
switch turns the history off (and forgets it).

The list is reloaded only when the history changed since the last opening;
image previews are decoded in a thread, scaled down (a 4K screenshot is not
kept in memory at full size by a panel that stays resident).
"""
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

from i18n import tr  # noqa: E402
from system import clipboard  # noqa: E402

THUMB_W, THUMB_H = 320, 120

CSS = """
list.clip-list { background: none; }
list.clip-list > row { border-radius: 12px; padding: 8px 6px 8px 12px; margin-bottom: 4px;
                       background: @surface_2; }
list.clip-list > row:hover { background: @hover; }
list.clip-list > row:selected, list.clip-list > row:focus { background: @accent_soft; outline: none; }
.clip-text { font-size: 13px; }
.clip-meta { font-size: 11px; color: @ink_dim; }
picture.clip-image { border-radius: 8px; }
button.clip-delete { min-width: 26px; min-height: 26px; padding: 0; border-radius: 999px;
                     background: none; border: none; box-shadow: none; opacity: 0.6; }
button.clip-delete:hover { background: @hover_2; opacity: 1; }
.clip-empty-title { font-size: 14px; font-weight: 500; }
"""


class Row(Gtk.ListBoxRow):
    def __init__(self, entry, on_delete):
        super().__init__()
        self.entry = entry
        box = Gtk.Box(spacing=8)
        if entry.image:
            self.picture = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN,
                                       hexpand=True, halign=Gtk.Align.START,
                                       css_classes=["clip-image"])
            self.picture.set_size_request(-1, min(THUMB_H, max(36, entry.size[1])))
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
            inner.append(self.picture)
            inner.append(Gtk.Label(label=tr("Image {width} × {height}").format(
                width=entry.size[0], height=entry.size[1]), xalign=0, css_classes=["clip-meta"]))
            box.append(inner)
        else:
            self.picture = None
            box.append(Gtk.Label(label=entry.text, xalign=0, hexpand=True, wrap=True,
                                 wrap_mode=Pango.WrapMode.WORD_CHAR, lines=3,
                                 ellipsize=Pango.EllipsizeMode.END, max_width_chars=40,
                                 css_classes=["clip-text"]))
        delete = Gtk.Button(css_classes=["clip-delete"], valign=Gtk.Align.START,
                            tooltip_text=tr("Delete (Del)"))
        delete.set_child(Gtk.Image(icon_name="zeta-close", pixel_size=14))
        delete.connect("clicked", lambda *_: on_delete(self))
        box.append(delete)
        self.set_child(box)

    def matches(self, words):
        if not words:
            return True
        low = (self.entry.text if not self.entry.image else "image " + self.entry.image).lower()
        return all(w in low for w in words)


class ClipboardView(Gtk.Box):
    """on_pick(data bytes, mime) is called with the chosen entry."""

    def __init__(self, on_pick):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.on_pick = on_pick
        self.loaded_stamp = False          # never loaded
        self.words = []
        self.thumbs = {}                   # entry id -> Gdk.Texture

        self.search = Gtk.SearchEntry(placeholder_text=tr("Search the clipboard history"),
                                      hexpand=True)
        self.search.add_css_class("zeta-entry")
        self.search.set_search_delay(60)
        self.search.connect("search-changed", self._filter_changed)
        self.search.connect("activate", lambda *_: self.pick_first())
        # capture: the entry's own text field would otherwise take the Down key
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._search_key)
        self.search.add_controller(keys)
        self.append(self.search)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE,
                                activate_on_single_click=True, css_classes=["clip-list"])
        self.list.set_filter_func(lambda row: row.matches(self.words))
        self.list.set_placeholder(Gtk.Label(label=tr("No matches"), css_classes=["zeta-dim"],
                                            margin_top=30))
        self.list.connect("row-activated", lambda _l, row: self.pick(row))
        lkeys = Gtk.EventControllerKey()
        lkeys.connect("key-pressed", self._list_key)
        self.list.add_controller(lkeys)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                    child=self.list)

        # empty history, or history turned off
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, vexpand=True,
                        valign=Gtk.Align.CENTER)
        empty.append(Gtk.Image(icon_name="zeta-clipboard", pixel_size=40, opacity=0.6))
        self.empty_title = Gtk.Label(css_classes=["clip-empty-title"], wrap=True,
                                     justify=Gtk.Justification.CENTER)
        self.empty_text = Gtk.Label(css_classes=["zeta-dim", "zeta-small"], wrap=True,
                                    justify=Gtk.Justification.CENTER, max_width_chars=36)
        self.turn_on = Gtk.Button(label=tr("Turn on"), halign=Gtk.Align.CENTER,
                                  css_classes=["zeta-primary"], margin_top=6)
        self.turn_on.connect("clicked", lambda *_: self.switch.set_active(True))
        for w in (self.empty_title, self.empty_text, self.turn_on):
            empty.append(w)

        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(scroll, "list")
        self.stack.add_named(empty, "empty")
        self.append(self.stack)

        foot = Gtk.Box(spacing=8)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER,
                                 tooltip_text=tr("When off, nothing you copy is saved "
                                                 "and the history is cleared"))
        self.switch_handler = self.switch.connect("notify::active", self._switched)
        foot.append(self.switch)
        foot.append(Gtk.Label(label=tr("Save history"), css_classes=["zeta-small"],
                              hexpand=True, xalign=0))
        self.clear = Gtk.Button(label=tr("Clear all"), css_classes=["zeta-flat", "zeta-small"])
        self.clear.connect("clicked", lambda *_: self.clear_all())
        foot.append(self.clear)
        self.append(foot)

    # --- opening ---
    def prepare(self):
        on = clipboard.enabled()
        with self.switch.handler_block(self.switch_handler):
            self.switch.set_active(on)
        self.search.set_text("")
        self.words = []
        if not on:
            self._show_empty(off=True)
            return
        stamp = clipboard.stamp()
        if stamp != self.loaded_stamp:
            self.reload()
        else:
            self.list.invalidate_filter()
            self._update_state()
        first = self._first_visible()
        if first is not None:
            self.list.select_row(first)

    def focus(self):
        self.search.grab_focus()

    def _rows(self):
        rows, i = [], 0
        while (row := self.list.get_row_at_index(i)) is not None:
            rows.append(row)
            i += 1
        return rows

    def reload(self):
        """Bring the list up to date. Usually one or two entries were added
        since the last opening (always the newest, at the top): only those
        rows are created and the vanished ones removed, instead of
        rebuilding up to 100 rows at every Super+V."""
        self.loaded_stamp = clipboard.stamp()
        found = clipboard.entries()
        existing = {row.entry.id: row for row in self._rows()}
        by_id = {e.id: e for e in found}
        # an id reused with different content (history wiped elsewhere):
        # start again from scratch
        if any(i in by_id and by_id[i].line != row.entry.line for i, row in existing.items()):
            self.list.remove_all()
            existing = {}
        for i, row in existing.items():
            if i not in by_id:
                self.list.remove(row)
        pos = 0
        for e in found:
            if e.id in existing:
                continue
            row = Row(e, self.delete_row)
            self.list.insert(row, pos)
            pos += 1
            if e.image:
                if e.id in self.thumbs:
                    row.picture.set_paintable(self.thumbs[e.id])
                else:
                    self._load_thumb(row)
        # previews of entries no longer in the history are forgotten
        self.thumbs = {k: v for k, v in self.thumbs.items() if k in by_id}
        self._update_state()

    def _update_state(self):
        has = self.list.get_row_at_index(0) is not None
        self.clear.set_sensitive(has)
        if has:
            self.stack.set_visible_child_name("list")
        else:
            self._show_empty(off=False)

    def _show_empty(self, off):
        if off:
            self.empty_title.set_text(tr("Clipboard history is off"))
            self.empty_text.set_text(tr("Turn it on to keep a list of what you copy. "
                                        "Passwords from password managers are never saved."))
        else:
            self.empty_title.set_text(tr("Nothing copied yet"))
            self.empty_text.set_text(tr("Copy text or an image and it will appear here. "
                                        "Press Super + V to open this list."))
        self.turn_on.set_visible(off)
        self.clear.set_sensitive(False)
        self.stack.set_visible_child_name("empty")

    # --- image previews ---
    def _load_thumb(self, row):
        entry_id = row.entry.id

        def work():
            data = clipboard.decode(entry_id)
            pixbuf = None
            if data:
                try:
                    loader = GdkPixbuf.PixbufLoader()

                    def size_prepared(ld, w, h):
                        scale = min(1.0, THUMB_W / max(1, w), THUMB_H / max(1, h))
                        ld.set_size(max(1, int(w * scale)), max(1, int(h * scale)))
                    loader.connect("size-prepared", size_prepared)
                    loader.write(data)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                except GLib.Error:
                    pixbuf = None
            GLib.idle_add(done, pixbuf)

        def done(pixbuf):
            if pixbuf is not None:
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.thumbs[entry_id] = texture
                if row.get_parent() is not None:
                    row.picture.set_paintable(texture)
            return False
        threading.Thread(target=work, daemon=True).start()

    # --- search and keyboard ---
    def _filter_changed(self, *_):
        self.words = self.search.get_text().lower().split()
        self.list.invalidate_filter()
        first = self._first_visible()
        if first is not None:
            self.list.select_row(first)

    def _first_visible(self, start=0):
        i = start
        while True:
            row = self.list.get_row_at_index(i)
            if row is None:
                return None
            if row.matches(self.words):
                return row
            i += 1

    def _search_key(self, _ctl, keyval, _code, _state):
        if keyval == Gdk.KEY_Down:
            # The highlighted entry is the one Enter pastes from the search
            # field; Down moves on to the next one (Down, Enter = the second
            # most recent copy, as on Windows).
            row = self.list.get_selected_row() or self._first_visible()
            if row is not None:
                row = self._first_visible(row.get_index() + 1) or row
                row.grab_focus()
                self.list.select_row(row)
                return True
        return False

    def _list_key(self, _ctl, keyval, _code, _state):
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            row = self.list.get_selected_row()
            if row is not None:
                self.delete_row(row)
                return True
        return False

    # --- actions ---
    def pick_first(self):
        row = self.list.get_selected_row() or self._first_visible()
        if row is not None:
            self.pick(row)

    def pick(self, row):
        data = clipboard.decode(row.entry.id)
        if not data:
            return
        mime = row.entry.mime()
        if row.entry.image:
            mime = clipboard.IMAGE_MIME.get(clipboard.sniff_image(data) or "", mime)
        self.on_pick(data, mime)

    def delete_row(self, row):
        index = row.get_index()
        clipboard.delete(row.entry)
        self.thumbs.pop(row.entry.id, None)
        self.list.remove(row)
        self.loaded_stamp = clipboard.stamp()
        nxt = self.list.get_row_at_index(index) or self.list.get_row_at_index(max(0, index - 1))
        if nxt is not None:
            self.list.select_row(nxt)
            nxt.grab_focus()
        else:
            self.search.grab_focus()
        self._update_state()

    def clear_all(self):
        clipboard.wipe()
        self.list.remove_all()
        self.thumbs.clear()
        self.loaded_stamp = clipboard.stamp()
        self._update_state()
        self.search.grab_focus()

    def _switched(self, sw, _param):
        on = sw.get_active()
        clipboard.set_enabled(on)
        self.loaded_stamp = False
        if on:
            self.reload()
        else:
            self.list.remove_all()
            self.thumbs.clear()
            self._show_empty(off=True)
