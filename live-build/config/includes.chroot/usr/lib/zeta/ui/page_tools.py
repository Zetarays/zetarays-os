# SPDX-License-Identifier: GPL-3.0-or-later
"""Small helpers shared by the newer Settings pages (Keyboard & Mouse,
Date & Time, Accessibility, Storage, Backup, Users, Firewall, ZETA WATCH…).

They stay light on purpose: a page imports this module, not the larger
settings_pages module with the network and audio code.
"""
import json
import os
import subprocess
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from i18n import language, tr  # noqa: E402


def bg(work, done=None):
    """Run work() in a thread, then done(result) in the UI thread."""
    def runner():
        try:
            res = work()
        except Exception as e:  # noqa: BLE001 - reported to the page, never lost
            res = e
        if done:
            GLib.idle_add(lambda: (done(res), False)[1])
    threading.Thread(target=runner, daemon=True).start()


def toast(widget, text):
    root = widget.get_root()
    if hasattr(root, "toast"):
        root.toast(text)


_CHILDREN = set()


def spawn(*cmd):
    """Start a program detached from Settings; False when it is missing.
    The program is reaped when it exits, so a closed window never stays
    behind as a zombie process while Settings is open."""
    try:
        p = subprocess.Popen(list(cmd), start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    _CHILDREN.add(p)                 # kept so Python does not reap it a second time

    def finished(_pid, state, proc=p):
        proc.returncode = state
        _CHILDREN.discard(proc)
    GLib.child_watch_add(GLib.PRIORITY_DEFAULT_IDLE, p.pid, finished)
    return True


def run_quiet(cmd, timeout=30):
    """Run a command and wait (call it in a thread); True on success."""
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def pkexec_helper(helper, *argv, timeout=900):
    """Run a /usr/libexec/zeta-* helper through pkexec (in a thread).

    Returns (ok, outcome dict); outcome is None when the user closed the
    password window. The helpers print one JSON line."""
    try:
        r = subprocess.run(["pkexec", helper, "--lang=%s" % language()] + list(argv),
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return False, {"error": str(e)}
    if r.returncode == 126:
        return False, None
    try:
        outcome = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        outcome = {}
    if r.returncode == 127 and not r.stdout.strip():
        return False, {"error": tr("The change needs an administrator's password, and it was not accepted.")}
    if r.returncode != 0 and not outcome.get("error"):
        outcome["error"] = tr("Not changed.")
    return r.returncode == 0, outcome


def scale_row(title, subtitle, lo, hi, step, value, on_change, marks=()):
    """An Adw.ActionRow with a slider; on_change(value) runs when it moves."""
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    scale.set_value(value)
    scale.set_draw_value(False)
    scale.set_hexpand(True)
    scale.set_size_request(220, -1)
    scale.set_valign(Gtk.Align.CENTER)
    for v, label in marks:
        scale.add_mark(v, Gtk.PositionType.BOTTOM, label)
    scale.connect("value-changed", lambda s: on_change(s.get_value()))
    row.add_suffix(scale)
    row.scale = scale
    return row


def confirm(widget, heading, body, ok_label, on_ok, destructive=False):
    dlg = Adw.AlertDialog(heading=heading, body=body)
    dlg.add_response("cancel", tr("Cancel"))
    dlg.add_response("ok", ok_label)
    dlg.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive
                                else Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("cancel" if destructive else "ok")
    dlg.set_close_response("cancel")
    dlg.connect("response", lambda _d, resp: on_ok() if resp == "ok" else None)
    dlg.present(widget.get_root())


def gsettings(schema):
    """Gio.Settings for a schema, or None when it is not installed."""
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(schema, True) is None:
        return None
    return Gio.Settings.new(schema)


def size_text(n):
    return GLib.format_size(max(0, int(n or 0)))


def write_if_changed(path, text):
    """Write a file atomically, only when its content changes. Hyprland
    reloads its configuration whenever a file it read changes: an
    identical rewrite would cost a reload for nothing."""
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def lua_literal(value):
    """A Lua literal for plain values: booleans, numbers, short identifier-like
    strings and tables of them. Anything else is refused: the generated
    files are run by the compositor."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return ("%.3f" % value).rstrip("0").rstrip(".") if value != int(value) else "%.1f" % value
    if isinstance(value, str):
        if not all(c.isalnum() or c in "_:,.-" for c in value) or len(value) > 64:
            raise ValueError("unsafe Lua string: %r" % value)
        return '"%s"' % value
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if not (isinstance(k, str) and k.replace("_", "a").isalnum() and not k[0].isdigit()):
                raise ValueError("unsafe Lua key: %r" % k)
            parts.append("%s = %s" % (k, lua_literal(v)))
        return "{ " + ", ".join(parts) + " }"
    raise ValueError("unsupported Lua value: %r" % (value,))


def hypr_eval(code):
    """Run Lua inside the running Hyprland (no effect outside a session)."""
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return
    spawn("hyprctl", "eval", code)
