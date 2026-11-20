# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS: clipboard history (Super+V) and pasting into the focused window.

No GTK here: zeta-clipboard's command line (enable, disable, status) and
zeta-selftest use it too.

- The history is kept by cliphist (Debian trixie 0.5.0) in
  ~/.cache/cliphist/db. The session saves every change through
  /usr/libexec/zeta-clipboard-store (it skips passwords and respects the
  on/off choice).
- The on/off choice is ~/.config/zeta/clipboard-history ("1" or "0"), like
  the other ZETA RAYS preferences (one small file per value).
- Pasting: the entry goes back to the clipboard (wl-copy), the panel hides,
  and Hyprland sends Ctrl+V straight to the window that had the focus
  (send_shortcut). Terminals paste with Ctrl+Shift+V. Not wtype: its virtual
  keyboard brings its own keymap, where "v" gets keycode 9; Hyprland matched
  the key bindings with the real keymap, read it as Escape, and Ctrl+Shift+V
  in a terminal became Ctrl+Shift+Esc (force-quit the active window).
"""
import json
import os
import re
import subprocess
import threading
import time

CFG = os.path.expanduser("~/.config/zeta/clipboard-history")
TEXT_MIME = "text/plain;charset=utf-8"

# cliphist shows an image as "[[ binary data 12 KiB png 800x600 ]]"
_IMAGE = re.compile(r"^\[\[ binary data (.+) (\w+) (\d+)x(\d+) \]\]$")
IMAGE_MIME = {"png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif",
              "bmp": "image/bmp", "webp": "image/webp"}

# Window classes that paste with Ctrl+Shift+V (Ctrl+V is a control key there)
TERMINALS = {"foot", "footclient", "kitty", "alacritty", "org.wezfurlong.wezterm",
             "com.mitchellh.ghostty", "xterm", "uxterm", "org.gnome.console",
             "gnome-terminal-server", "org.gnome.terminal", "org.kde.konsole", "konsole",
             "com.gexperts.tilix", "terminator", "xfce4-terminal", "lxterminal"}


def _db():
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(cache, "cliphist", "db")


def enabled():
    """Clipboard history on (the default) or off."""
    try:
        with open(CFG) as f:
            return f.read().strip() != "0"
    except OSError:
        return True


def set_enabled(on):
    """Turn the history on or off. Off also forgets what was saved: the
    user turning it off does not want the old entries kept either."""
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    with open(CFG, "w") as f:
        f.write("1" if on else "0")
    if not on:
        wipe()


def stamp():
    """Changes whenever the history changes (to reload it only then)."""
    try:
        st = os.stat(_db())
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _cliphist(args, data=None, timeout=5):
    try:
        r = subprocess.run(["cliphist"] + args, input=data, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


class Entry:
    """One entry of the history: id, the line cliphist printed, a text
    preview (first 100 bytes) or the image format and size."""
    __slots__ = ("id", "line", "text", "image", "size")

    def __init__(self, line):
        self.line = line
        ident, _tab, preview = line.partition("\t")
        self.id = int(ident)
        m = _IMAGE.match(preview)
        if m and m.group(2) in IMAGE_MIME:
            self.image = m.group(2)
            self.size = (int(m.group(3)), int(m.group(4)))
            self.text = ""
        else:
            self.image = None
            self.size = None
            self.text = preview

    def mime(self):
        return IMAGE_MIME[self.image] if self.image else TEXT_MIME


def entries():
    """The history, newest first."""
    if stamp() is None:
        return []
    out = _cliphist(["list"])
    if not out:
        return []
    found = []
    for line in out.decode("utf-8", "replace").splitlines():
        ident = line.partition("\t")[0]
        if ident.isdigit():
            found.append(Entry(line))
    return found


def decode(entry_id):
    """The full content of an entry (bytes)."""
    return _cliphist(["decode", str(int(entry_id))]) or b""


def delete(entry):
    _cliphist(["delete"], data=(entry.line + "\n").encode("utf-8", "replace"))


def wipe():
    if stamp() is not None:
        _cliphist(["wipe"])


def count():
    return len(entries())


def status():
    """For Settings and scripts: {"enabled": true, "entries": 12}."""
    return {"enabled": enabled(), "entries": count() if enabled() else 0}


def copy(data, mime=TEXT_MIME):
    """Put data on the clipboard. wl-copy stays in the background to serve
    it: its output must not be a pipe of ours, or waiting for it would hang."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    try:
        p = subprocess.Popen(["wl-copy", "--type", mime], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        p.communicate(data, timeout=5)
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def active_window():
    """(class, address) of the focused window (("", "") when none)."""
    try:
        out = subprocess.run(["hyprctl", "-j", "activewindow"], capture_output=True,
                             text=True, timeout=2).stdout
        w = json.loads(out or "{}")
        return ((w.get("class") or "").strip(), (w.get("address") or "").strip())
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return ("", "")


def active_class():
    """Class of the focused window ("" when no window has the focus)."""
    return active_window()[0]


def paste_mods(window_class):
    """Modifiers of "paste" in a window of this class."""
    return "CTRL SHIFT" if window_class.lower() in TERMINALS else "CTRL"


def paste_command(window_class, address):
    """hyprctl command that sends the paste shortcut to that window only,
    None for an address that is not a Hyprland window address."""
    if not re.fullmatch(r"0x[0-9a-fA-F]{1,16}", address or ""):
        return None
    return ["hyprctl", "dispatch",
            'hl.dsp.send_shortcut({ mods = "%s", key = "V", window = "address:%s" })'
            % (paste_mods(window_class), address)]


def paste_later(delay=0.15, done=None):
    """Send the paste shortcut to the focused window, after the panel has
    gone and the window has the keyboard back. In a thread: never blocks the
    UI. done(pasted) is called (from the thread) at the end."""
    def work():
        time.sleep(delay)
        cls, address = active_window()
        cmd = paste_command(cls, address) if cls else None
        ok = False
        if cmd:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                ok = r.returncode == 0 and "ok" in r.stdout.lower()
            except (OSError, subprocess.SubprocessError):
                ok = False
        if done:
            done(ok)
    threading.Thread(target=work, daemon=True).start()


def sniff_image(data):
    """Image format from the first bytes (None if not an image)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data.startswith(b"BM"):
        return "bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None
