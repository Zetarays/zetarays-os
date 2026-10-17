# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — window management (Hyprland).

Hyprland has no "minimize": we implement it here by moving the window to a
hidden special workspace and remembering where it came from, so the title
bar's "minimize" button really does something and the window can be reopened
from the bottom bar.
"""
import json
import os
import signal
import subprocess
import time

from i18n import ntr, tr

HIDDEN = "special:zetamin"
STATE = os.path.expanduser("~/.cache/zeta/windows.json")


def _hyprctl(args, as_json=False):
    try:
        out = subprocess.run(["hyprctl"] + (["-j"] if as_json else []) + args,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    if not as_json:
        return out.stdout.strip()
    try:
        return json.loads(out.stdout)
    except ValueError:
        return None


def dispatch(lua):
    """Run a Hyprland 0.55 dispatcher (Lua syntax). True on success."""
    r = _hyprctl(["dispatch", lua])
    return r is not None and "invalid" not in (r or "").lower()


def clients():
    return _hyprctl(["clients"], as_json=True) or []


def active():
    w = _hyprctl(["activewindow"], as_json=True)
    return w if isinstance(w, dict) and w.get("address") else None


def _load():
    try:
        with open(STATE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _notify_bar():
    """Refresh the counter in the bar right away (SIGRTMIN+9)."""
    subprocess.run(["pkill", "-RTMIN+9", "-x", "waybar"],
                   capture_output=True, check=False)


def _save(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, STATE)
    _notify_bar()


def _sel(addr):
    return "address:%s" % addr


# ---------------------------------------------------------------- previews
# Minimized windows show up in the bar as thumbnails (like the macOS Dock),
# not as "1 minimized". The image is captured just before hiding the window,
# while it is still on screen: afterwards it is no longer drawn.
PREVIEWS = os.path.expanduser("~/.cache/zeta/minimized")
SLOTS = 8                                  # maximum number of thumbnails in the bar
ASPECT_RATIO = 1.6                             # thumbnail width / height


TITLE_BAR_HEIGHT = 32                          # hyprbars (bar_height in hyprland.lua)


def rectangle(win):
    """(x, y, w, h) of the window as it appears, title bar included
    (Hyprland draws it above the window's coordinates; in full screen there
    is none)."""
    try:
        (x, y), (w, h) = win["at"], win["size"]
    except (KeyError, TypeError, ValueError):
        return None
    if not win.get("fullscreen") and y >= TITLE_BAR_HEIGHT:
        y, h = y - TITLE_BAR_HEIGHT, h + TITLE_BAR_HEIGHT
    return (x, y, w, h)


def capture(win, dest):
    """Capture an image of the window (it must be visible). Returns the
    rectangle used, or None."""
    r = rectangle(win)
    if not r or r[2] < 8 or r[3] < 8:
        return None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        p = subprocess.run(["grim", "-l", "0", "-g", "%d,%d %dx%d" % r, dest],
                           capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r if p.returncode == 0 and os.path.exists(dest) else None


def _app_icon(class_name):
    try:
        import sys
        if "/usr/lib/zeta" not in sys.path:
            sys.path.insert(0, "/usr/lib/zeta")
        from system import applications
        c = (class_name or "").lower()
        for a in applications.all_apps():
            names = {a.wm_class.lower(), a.id[:-8].lower(), os.path.basename(a.executable).lower()}
            if c and c in names and a.icon:
                p = applications.icon_file(a.icon)
                return p if os.path.exists(p) else None
    except Exception:  # noqa: BLE001 - the thumbnail is still fine without an icon
        return None
    return None


def compose_preview(capture_png, dest, class_name="", height=84):
    """Rounded thumbnail with the app icon in the corner (PNG, 2x)."""
    import cairo
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, GdkPixbuf
    W, H = int(height * ASPECT_RATIO), height
    sup = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(sup)

    def rect(x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -1.5708, 0)
        cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
        cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
        cr.arc(x + r, y + r, r, 3.1416, 4.7124)
        cr.close_path()
    m = 3
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(capture_png)
        sc = min((W - 2 * m) / pb.get_width(), (H - 2 * m) / pb.get_height())
        pw, ph = max(1, int(pb.get_width() * sc)), max(1, int(pb.get_height() * sc))
        pb = pb.scale_simple(pw, ph, GdkPixbuf.InterpType.BILINEAR)
    except Exception:  # noqa: BLE001
        pb, pw, ph = None, W - 2 * m, H - 2 * m
    ox, oy = (W - pw) / 2, (H - ph) / 2
    cr.save()
    rect(ox, oy, pw, ph, 7)
    cr.clip()
    if pb is not None:
        Gdk.cairo_set_source_pixbuf(cr, pb, ox, oy)
    else:
        cr.set_source_rgb(0.12, 0.12, 0.13)
    cr.paint()
    cr.restore()
    rect(ox + 0.5, oy + 0.5, pw - 1, ph - 1, 7)
    cr.set_source_rgba(1, 1, 1, 0.18)
    cr.set_line_width(1)
    cr.stroke()
    icon = _app_icon(class_name)
    if icon:
        try:
            side = int(H * 0.46)
            ib = GdkPixbuf.Pixbuf.new_from_file_at_size(icon, side, side)
            Gdk.cairo_set_source_pixbuf(cr, ib, W - ib.get_width() - 1, H - ib.get_height() - 1)
            cr.paint()
        except Exception:  # noqa: BLE001
            pass
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp.png"
    sup.write_to_png(tmp)
    os.replace(tmp, dest)
    return dest


def _preview_file(addr, kind):
    return os.path.join(PREVIEWS, "%s-%s.png" % (addr.replace("0x", ""), kind))


def remove_preview(addr):
    for kind in ("mini", "large"):
        try:
            os.unlink(_preview_file(addr, kind))
        except OSError:
            pass


def minimized_in_order():
    """The minimized windows, in bar order, from the state file only
    (no hyprctl: the bar reads this on every refresh)."""
    return list(_load().items())


def forget(addr):
    """A minimized window is gone (closed): drop it from the state and the bar."""
    remove_preview(addr)
    state = _load()
    if addr in state:
        state.pop(addr, None)
        _save(state)


def minimize(addr=None):
    """Hide the window (the active one if addr is None). True if done."""
    win = None
    if addr is None:
        win = active()
        if not win:
            return False
        addr = win["address"]
    else:
        for c in clients():
            if c.get("address") == addr:
                win = c
                break
        if win is None:
            return False
    ws = (win.get("workspace") or {}).get("name") or ""
    if ws.startswith("special:"):
        return False                      # already hidden
    state = _load()
    state[addr] = {"workspace": ws or "1",
                   "title": win.get("title") or "",
                   "class": win.get("class") or "",
                   "rect": rectangle(win),
                   "time": time.time()}
    _save(state)
    ok = dispatch('hl.dsp.window.move({ workspace = "%s", follow = false, window = "%s" })'
                  % (HIDDEN, _sel(addr)))
    if not ok:
        state.pop(addr, None)
        _save(state)
    return ok


def title_bars_present():
    """True when the windows have title bars with their buttons (hyprbars).

    hyprland.lua writes "1" at every configuration load when the buttons are
    registered. Otherwise the plugin list is asked: at login the plugin is
    loaded but its buttons only arrive with the reload zeta-session does two
    seconds later, and the bar must not flash a Windows button meanwhile.
    Without title bars the bar shows the Windows button, so that every
    window can still be closed and minimized with the mouse."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    try:
        with open(os.path.join(runtime, "zeta-title-bars")) as f:
            if f.read().strip() == "1":
                return True
    except OSError:
        pass
    out = _hyprctl(["plugin", "list"])
    return out is None or "hyprbars" in out.lower()


def _active_workspace():
    ws = _hyprctl(["activeworkspace"], as_json=True)
    name = str((ws or {}).get("name") or "") if isinstance(ws, dict) else ""
    return name if name and not name.startswith("special:") else ""


def _placeholder_preview(addr, class_name):
    """Thumbnail without a snapshot (dark card with the app icon), for a
    minimized window whose snapshot is missing: it can no longer be
    captured, since a hidden window is not drawn."""
    try:
        compose_preview(os.path.join(PREVIEWS, "-none-.png"), _preview_file(addr, "mini"), class_name)
    except Exception:  # noqa: BLE001 - the window stays in the list anyway
        pass


ADOPT_AFTER = 10            # seconds: zeta-minimize writes the snapshot meanwhile


def minimized():
    """List of minimized windows that still exist (the others are removed).

    Windows on a hidden (special) workspace that the state file does not
    know are adopted: zeta-minimize may have crashed, the state file may
    have been deleted, or a program may have moved itself there. Without
    this they would be in neither list, unreachable."""
    state = _load()
    all_clients = _hyprctl(["clients"], as_json=True)
    if not isinstance(all_clients, list):
        # Hyprland did not answer (busy computer): forget nothing
        return [{"address": a, "title": i.get("title") or tr("Window"),
                 "class": i.get("class") or "", "workspace": i.get("workspace") or ""}
                for a, i in state.items()]
    live = {c.get("address"): c for c in all_clients}
    changed = False
    for c in all_clients:
        addr = c.get("address")
        ws = str((c.get("workspace") or {}).get("name", ""))
        if addr and ws.startswith("special:") and addr not in state and c.get("mapped", True):
            # restored to the workspace on screen at that moment
            state[addr] = {"workspace": "", "title": c.get("title") or "",
                           "class": c.get("class") or "", "rect": None,
                           "adopted": True}
            changed = True
    if not state:
        return []
    now = time.time()
    out = []
    for addr, info in list(state.items()):
        c = live.get(addr)
        if c is None:
            state.pop(addr, None)
            remove_preview(addr)
            changed = True
            continue
        if not str((c.get("workspace") or {}).get("name", "")).startswith("special:"):
            # the user brought it back some other way
            state.pop(addr, None)
            remove_preview(addr)
            changed = True
            continue
        if (not os.path.exists(_preview_file(addr, "mini"))
                and (info.get("adopted") or now - float(info.get("time") or 0) > ADOPT_AFTER)):
            _placeholder_preview(addr, c.get("class") or info.get("class") or "")
        out.append({"address": addr,
                    "title": c.get("title") or info.get("title") or tr("Window"),
                    "class": c.get("class") or info.get("class") or "",
                    "workspace": info.get("workspace") or ""})
    if changed:
        _save(state)
    return out


def restore(addr):
    """Move the window back to its workspace and give it focus. A window
    with no known workspace (adopted from a hidden workspace) comes back to
    the one on screen. The window guard in hyprland.lua then makes sure it
    is reachable, even if its old place was on a display that is gone."""
    state = _load()
    ws = (state.get(addr) or {}).get("workspace") or _active_workspace() or "1"
    ok = dispatch('hl.dsp.window.move({ workspace = "%s", follow = false, window = "%s" })'
                  % (ws, _sel(addr)))
    if ok:
        remove_preview(addr)            # before notifying the bar
        state.pop(addr, None)
        _save(state)
        dispatch('hl.dsp.focus({ workspace = "%s" })' % ws)
        dispatch('hl.dsp.focus({ window = "%s" })' % _sel(addr))
    return ok


def focus(addr):
    return dispatch('hl.dsp.focus({ window = "%s" })' % _sel(addr))


def recover_all():
    """Every window back inside the screen, title bar and buttons within
    reach; full screen windows leave full screen (the window guard in
    hyprland.lua, the same as Super+Shift+W)."""
    return _hyprctl(["eval", "if zeta_recover then zeta_recover() end"]) is not None


def close(addr=None):
    if addr is None:
        return dispatch("hl.dsp.window.close()")
    return dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(addr))


def toggle_maximize(addr=None):
    tgt = ", window = \"%s\"" % _sel(addr) if addr else ""
    return dispatch('hl.dsp.window.fullscreen({ mode = "maximized"%s })' % tgt)


def open_windows():
    """Visible (not minimized) windows, most recent first."""
    out = []
    for c in clients():
        ws = str((c.get("workspace") or {}).get("name", ""))
        if ws.startswith("special:"):
            continue
        out.append({"address": c.get("address"), "title": c.get("title") or tr("Window"),
                    "class": c.get("class") or "", "workspace": ws,
                    "pid": c.get("pid") or 0})
    out.sort(key=lambda w: w["workspace"])
    return out


def memory_mb(pid):
    """How much memory a process uses, in MB (0 if it can't be read)."""
    try:
        with open("/proc/%d/statm" % int(pid)) as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        return 0.0


def stuck_on_disk(pid):
    """True if the process is stuck waiting for the disk or a driver.

    This is the "D" state: the process doesn't respond and can't even be
    interrupted until the kernel gives it what it is waiting for. It is the
    only "not responding" that can be stated by looking at the system, which
    is why it is the only one shown: inventing a diagnosis would make things
    worse instead of helping.
    """
    try:
        with open("/proc/%d/stat" % int(pid)) as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return fields[0] == "D"
    except (OSError, ValueError, IndexError):
        return False


# Desktop components that are never terminated from here: stopping them would
# lose the whole session, and the cure would be worse than the disease.
PROTECTED = {"Hyprland", "Xwayland", "waybar", "mako", "swaybg", "zeta-session",
            "zeta-watchdog", "systemd", "dbus-daemon", "dbus-broker", "sddm",
            "sddm-helper", "pipewire", "pipewire-pulse", "wireplumber",
            "xdg-desktop-por", "xdg-document-po", "xdg-permission-", "polkit-mate-aut",
            "gnome-keyring-d", "sshd", "sshd-session", "login", "agetty"}


def _comm(pid):
    try:
        with open("/proc/%d/comm" % pid) as f:
            return f.read().strip()
    except OSError:
        return ""


def _direct_children():
    """ppid -> [pid] for every process, read from /proc in a single pass."""
    mapping = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % entry) as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        mapping.setdefault(ppid, []).append(int(entry))
    return mapping


def tree(pid):
    """The process and all of its descendants owned by the same user.

    A program often launches others (Firefox its tab processes, the terminal
    the command running inside it): terminating only the first one left the
    others alive, and the hang remained.
    """
    my_uid = os.getuid()
    mapping = _direct_children()
    seen, queue = [], [pid]
    while queue:
        p = queue.pop()
        if p in seen:
            continue
        try:
            if os.stat("/proc/%d" % p).st_uid != my_uid:
                continue
        except OSError:
            continue
        seen.append(p)
        queue.extend(mapping.get(p, []))
    return seen


def is_protected(pid):
    return int(pid) <= 1 or int(pid) == os.getpid() or _comm(int(pid)) in PROTECTED


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie is already dead: it is just waiting for its parent to reap it
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def force_quit(pid, wait=3.0, force=True):
    """End a frozen program together with its child processes: gently first,
    then by force.

    TERM is sent and we wait: a program that still responds saves and exits
    by itself. If it is still there after a few seconds it really isn't
    responding, so KILL follows. Starting straight with KILL would lose unsaved
    work even for programs that would have closed by themselves.
    With force=False we stop at TERM: that is the normal close ("close"),
    which must never become forcible unless the user asks for it.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False, tr("Invalid process.")
    if is_protected(pid):
        return False, tr("This process is part of the desktop and can't be ended from here.")
    all_processes = [p for p in tree(pid) if not is_protected(p)]
    if not all_processes:
        if not _alive(pid):
            return True, tr("It had already quit.")
        return False, tr("You don't have permission to end this process.")
    # the main process first (it may close its children in order), then the rest
    for p in all_processes:
        try:
            os.kill(p, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and any(_alive(p) for p in all_processes):
        time.sleep(0.15)
    remaining = [p for p in all_processes if _alive(p)]
    if not remaining:
        if len(all_processes) > 1:
            return True, ntr("Closed (with {n} related process).",
                             "Closed (with {n} related processes).",
                             len(all_processes) - 1).format(n=len(all_processes) - 1)
        return True, tr("Closed.")
    if not force:
        return False, tr("It didn't close on its own.")
    for p in remaining:
        try:
            os.kill(p, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    kill_deadline = time.monotonic() + 2.0
    while time.monotonic() < kill_deadline and any(_alive(p) for p in remaining):
        time.sleep(0.1)
    still_alive = [p for p in remaining if _alive(p)]
    if not still_alive:
        if len(all_processes) > 1:
            return True, ntr("Forced to quit (with {n} related process).",
                             "Forced to quit (with {n} related processes).",
                             len(all_processes) - 1).format(n=len(all_processes) - 1)
        return True, tr("Forced to quit.")
    if any(stuck_on_disk(p) for p in still_alive):
        return False, tr("The process doesn't respond even to a forced quit: the kernel "
                         "is holding it while it waits for the disk. It will close as "
                         "soon as the disk responds.")
    return False, tr("Couldn't end it.")


def window_at_point(x, y):
    """The visible window under the screen point (x, y).

    If several windows overlap, the most recently used one wins, since it is
    the one in front. Only windows on the displayed workspace are considered.
    """
    monitor = _hyprctl(["monitors"], as_json=True) or []
    active_ids = {m.get("activeWorkspace", {}).get("id") for m in monitor}
    active_ids |= {m.get("specialWorkspace", {}).get("id") for m in monitor
               if m.get("specialWorkspace", {}).get("id")}
    candidates = []
    for c in clients():
        if not c.get("mapped", True) or c.get("hidden"):
            continue
        if (c.get("workspace") or {}).get("id") not in active_ids and not c.get("pinned"):
            continue
        (cx, cy), (w, h) = c.get("at", (0, 0)), c.get("size", (0, 0))
        if cx <= x < cx + w and cy <= y < cy + h:
            candidates.append(c)
    if not candidates:
        return None
    return min(candidates, key=lambda c: c.get("focusHistoryID", 999))


def heavy_processes(threshold_mb=250):
    """The user's windowless processes that use a lot of memory: a frozen
    window isn't the only way a program can bog down the computer."""
    with_window = {c.get("pid") for c in clients()}
    my_uid = os.getuid()
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            if os.stat("/proc/%d" % pid).st_uid != my_uid:
                continue
        except OSError:
            continue
        if pid in with_window or is_protected(pid):
            continue
        mb = memory_mb(pid)
        if mb >= threshold_mb:
            out.append({"pid": pid, "name": _comm(pid), "mb": mb})
    out.sort(key=lambda d: -d["mb"])
    return out[:8]
