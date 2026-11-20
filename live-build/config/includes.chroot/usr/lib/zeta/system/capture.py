# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — screenshots and screen recordings, without GTK.

Everything here is plain Python and standard tools (grim, slurp, wl-copy,
wf-recorder, notify-send, tesseract, swappy, hyprpicker), so the commands
behind the keyboard shortcuts start in a few tens of milliseconds: GTK is
loaded only by the toolbar, the post-capture card and the recording
indicator (zeta-screenshot).

Files:
  ~/.config/zeta/screenshot.json        toolbar options (save, copy, pointer,
                                        sound, timer)
  $XDG_RUNTIME_DIR/zeta-screenshot/     recording state, thumbnails and
                                        captures not saved to a file
"""
import hashlib
import html
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse

from i18n import ntr, tr

APP_ID = "org.zetarays.Screenshot"
FREE_SPACE_MIN = 1 << 30                 # a recording stops below 1 GB free
DELAYS = (0, 3, 5, 10)
DEFAULTS = {"save": True, "copy": True, "pointer": False, "audio": False, "delay": 0}
SCREENSHOT_STEM = "Screenshot"           # file names are not translated
RECORDING_STEM = "Screen recording"
TEMP_KEEP = 10                           # unsaved captures kept in the runtime folder
DEVNULL = subprocess.DEVNULL


# ------------------------------------------------------------------ places
def runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    if not os.path.isdir(base):
        base = tempfile.gettempdir()
        name = "zeta-screenshot-%d" % os.getuid()
    else:
        name = "zeta-screenshot"
    d = os.path.join(base, name)
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _user_dir(kind, fallback):
    """xdg-user-dir answers $HOME when the folder is not configured."""
    home = os.path.expanduser("~")
    try:
        p = subprocess.run(["xdg-user-dir", kind], capture_output=True, text=True,
                           timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        p = ""
    if not p or not os.path.isabs(p) or os.path.normpath(p) == os.path.normpath(home):
        p = os.path.join(home, fallback)
    return p


def screenshots_dir():
    return os.path.join(_user_dir("PICTURES", "Pictures"), "Screenshots")


def recordings_dir():
    return os.path.join(_user_dir("VIDEOS", "Videos"), "Screen recordings")


def ensure_folder(path):
    os.makedirs(path, exist_ok=True)
    return path


def unique_path(folder, stem, ext, when=None):
    """"<stem> YYYY-MM-DD HH-MM-SS<ext>", with " (2)", " (3)"... when a file
    with that name exists. The name is reserved (an empty file is created)
    so that two captures in the same second never overwrite each other."""
    stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(time.time() if when is None else when))
    base = "%s %s" % (stem, stamp)
    n = 1
    while True:
        name = base + ext if n == 1 else "%s (%d)%s" % (base, n, ext)
        path = os.path.join(folder, name)
        try:
            with open(path, "x"):
                pass
            return path
        except FileExistsError:
            n += 1


def discard(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def is_saved(path):
    """False for a capture kept only in the runtime folder (not saved)."""
    return not os.path.abspath(path).startswith(runtime_dir() + os.sep)


def _prune_temporary():
    d = runtime_dir()
    try:
        files = sorted((f for f in os.listdir(d) if f.startswith(SCREENSHOT_STEM)),
                       key=lambda f: os.path.getmtime(os.path.join(d, f)))
    except OSError:
        return
    for f in files[:-TEMP_KEEP]:
        discard(os.path.join(d, f))


# ------------------------------------------------------------------ options
def _settings_path():
    return os.path.expanduser("~/.config/zeta/screenshot.json")


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(_settings_path()) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    if isinstance(d, dict):
        for k, v in DEFAULTS.items():
            if k in d and type(d[k]) is type(v):
                s[k] = d[k]
    if s["delay"] not in DELAYS:
        s["delay"] = 0
    return s


def save_settings(s):
    path = _settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    clean = {k: s.get(k, v) for k, v in DEFAULTS.items()}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(clean, f)
    os.replace(tmp, path)


# ------------------------------------------------------------------ Hyprland
def _hypr(what):
    try:
        r = subprocess.run(["hyprctl", "-j", what], capture_output=True, text=True, timeout=3)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def monitor_rects(mons=None):
    """[{name, x, y, w, h, focused}] in logical (scaled) coordinates, the
    ones grim, slurp and wf-recorder use."""
    out = []
    for m in (mons if mons is not None else _hypr("monitors")) or []:
        try:
            scale = float(m.get("scale") or 1)
            w, h = m["width"] / scale, m["height"] / scale
            if m.get("transform", 0) % 2:
                w, h = h, w
            out.append({"name": m["name"], "x": int(m.get("x", 0)), "y": int(m.get("y", 0)),
                        "w": int(round(w)), "h": int(round(h)), "focused": bool(m.get("focused")),
                        "workspaces": {(m.get("activeWorkspace") or {}).get("id"),
                                       (m.get("specialWorkspace") or {}).get("id")} - {None, 0}})
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    return out


def monitor_at(rects, x, y):
    for m in rects:
        if m["x"] <= x < m["x"] + m["w"] and m["y"] <= y < m["y"] + m["h"]:
            return m
    return next((m for m in rects if m["focused"]), rects[0] if rects else None)


def monitor_under_pointer():
    rects = monitor_rects()
    cur = _hypr("cursorpos") or {}
    m = monitor_at(rects, cur.get("x", -1), cur.get("y", -1)) if rects else None
    return m


def window_rect(c, title_bars=True):
    """(x, y, w, h) of a window as it appears on screen (with its title bar)."""
    from system import windows
    if title_bars:
        return windows.rectangle(c)
    try:
        (x, y), (w, h) = c["at"], c["size"]
        return (x, y, w, h)
    except (KeyError, TypeError, ValueError):
        return None


def _title_bars():
    from system import windows
    return windows.title_bars_present()


def visible_window_rects():
    """The windows on the workspaces shown right now (minimized ones are on a
    hidden workspace and are left out)."""
    visible = set()
    for m in monitor_rects():
        visible |= m["workspaces"]
    bars = _title_bars()
    out = []
    for c in _hypr("clients") or []:
        if not c.get("mapped", True) or c.get("hidden"):
            continue
        if (c.get("workspace") or {}).get("id") not in visible:
            continue
        r = window_rect(c, bars)
        if r and r[2] >= 8 and r[3] >= 8:
            out.append(r)
    return out


def active_window_rect():
    c = _hypr("activewindow")
    if not isinstance(c, dict) or not c.get("address"):
        return None
    return window_rect(c, _title_bars())


def geometry(rect):
    x, y, w, h = (int(v) for v in rect)
    return "%d,%d %dx%d" % (x, y, w, h)


def parse_geometry(text):
    """"x,y wxh" -> (x, y, w, h), or None."""
    try:
        pos, size = text.strip().split(" ", 1)
        x, y = (int(v) for v in pos.split(","))
        w, h = (int(v) for v in size.split("x"))
    except (ValueError, AttributeError):
        return None
    return (x, y, w, h) if w > 0 and h > 0 else None


# ------------------------------------------------------------------ selection
def _slurp_colors():
    """Selection colors: the window boxes take the system accent color."""
    try:
        from ui import accent
        box = accent.color_hex() + "33"
    except Exception:  # noqa: BLE001 - only a color: never block a capture
        box = "#3A8DFF33"
    return ["-b", "#00000055", "-c", "#FFFFFFDD", "-s", "#FFFFFF10", "-B", box, "-w", "2"]


def _slurp(args, boxes=None):
    """Geometry chosen with the mouse, None when canceled (Esc)."""
    try:
        r = subprocess.run(["slurp"] + _slurp_colors() + args, capture_output=True, text=True,
                           input="".join("%s\n" % geometry(b) for b in boxes or []), timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not parse_geometry(r.stdout):
        return None
    return r.stdout.strip()


def select_region():
    return _slurp(["-d"])


def select_window():
    boxes = visible_window_rects()
    if not boxes:
        return None
    return _slurp(["-r"], boxes)


def select_for_recording():
    """A click picks a whole screen, a drag picks an area."""
    return _slurp(["-d", "-o"])


# ------------------------------------------------------------------ capture
def grab(dest, geometry_text=None, output=None, pointer=False):
    """Write a PNG of the area / screen / all screens. (ok, error)."""
    cmd = ["grim", "-l", "3"]
    if pointer:
        cmd.append("-c")
    if geometry_text:
        cmd += ["-g", geometry_text]
    elif output:
        cmd += ["-o", output]
    cmd.append(dest)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    ok = r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0
    return ok, (r.stderr or "").strip().splitlines()[-1] if not ok and r.stderr.strip() else ""


def wait(delay):
    """The timer: a notification says when the capture starts; it closes a
    second before, so that it is not in the picture."""
    if not delay:
        return
    if delay >= 2:
        notify(ntr("Capture in {n} second", "Capture in {n} seconds", delay).format(n=delay),
               timeout=(delay - 1) * 1000)
    time.sleep(delay)


def png_size(path):
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def take(mode, delay=0, save=True, copy=True, pointer=False, folder=None, all_screens=False,
         active=False):
    """Run a screenshot. Returns (path, error): (None, None) = canceled."""
    wait(delay)
    target = None
    output = None
    if mode == "region":
        target = select_region()
        if target is None:
            return None, None
    elif mode == "window":
        if active:
            r = active_window_rect()
            if r is None:
                return None, tr("There is no active window.")
            target = geometry(r)
        else:
            boxes = visible_window_rects()
            if not boxes:
                return None, tr("There are no windows to capture.")
            target = _slurp(["-r"], boxes)
            if target is None:
                return None, None
    elif mode == "screen":
        if not all_screens:
            m = monitor_under_pointer()
            output = m["name"] if m else None
    else:
        return None, "unknown mode %s" % mode
    if save:
        folder = ensure_folder(folder or screenshots_dir())
    else:
        folder = runtime_dir()
        _prune_temporary()
    dest = unique_path(folder, SCREENSHOT_STEM, ".png")
    ok, err = grab(dest, target, output, pointer)
    if not ok:
        discard(dest)
        return None, err or tr("The screen could not be captured.")
    if copy:
        copy_image(dest)
    return dest, None


# ------------------------------------------------------------------ clipboard
def copy_image(path):
    """wl-copy stays in the background to serve the clipboard: its output
    must not be a pipe, or we would wait for it forever."""
    try:
        with open(path, "rb") as f:
            subprocess.run(["wl-copy", "--type", "image/png"], stdin=f, stdout=DEVNULL,
                           stderr=DEVNULL, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def copy_text(text):
    try:
        subprocess.run(["wl-copy", "--type", "text/plain;charset=utf-8"], input=text.encode(),
                       stdout=DEVNULL, stderr=DEVNULL, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------------ notifications
def notify(summary, body="", icon=None, actions=(), timeout=6000):
    """Show a notification. With actions, wait until it is closed and return
    the key of the chosen action ("" when none). mako runs the "default"
    action on a click; the others are offered by notification daemons
    that show buttons."""
    cmd = ["notify-send", "-a", "ZETA RAYS", "-t", str(timeout)]
    if icon:
        cmd += ["-i", icon]
    for key, label in actions:
        cmd += ["-A", "%s=%s" % (key, label)]
    cmd += [summary, html.escape(body, quote=False)]
    if not actions:
        try:
            subprocess.Popen(cmd, stdout=DEVNULL, stderr=DEVNULL, stdin=DEVNULL,
                             start_new_session=True)
        except OSError:
            pass
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout / 1000 + 600)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip()


def background():
    """Detach: the caller (a shortcut, a terminal) gets its answer at once,
    while the child stays to wait for the notification or the recording.
    True in the child, False in the parent, None if fork failed (then the
    caller does the work itself, in the foreground)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError, AttributeError):
            pass
    try:
        pid = os.fork()
    except OSError:
        return None
    if pid:
        return False
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    return True


def gvariant_string(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def ask_app(action, argument=None, start=True):
    """Send an action to the toolbar process if it is running (fast: no
    Python start); otherwise start it with that request (start=True)."""
    cmd = ["gapplication", "action", APP_ID, action]
    if argument is not None:
        cmd.append(gvariant_string(argument))
    try:
        if subprocess.run(cmd, stdout=DEVNULL, stderr=DEVNULL, timeout=5).returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    if not start:
        return False
    from system import spawn
    return spawn(["zeta-screenshot", "_app", action] + ([argument] if argument is not None else []))


def screenshot_actions(saved):
    acts = [("default", tr("Open")), ("edit", tr("Edit")), ("text", tr("Copy Text"))]
    if saved:
        acts += [("folder", tr("Open Folder")), ("delete", tr("Delete"))]
    else:
        acts += [("save", tr("Save"))]
    return acts


def notify_screenshot(path, copied):
    saved = is_saved(path)
    if saved and copied:
        summary = tr("Screenshot saved and copied")
    elif saved:
        summary = tr("Screenshot saved")
    else:
        summary = tr("Screenshot copied to the clipboard")
    body = tr("Click for Edit, Copy Text and more.")
    return notify(summary, body, icon=path, actions=screenshot_actions(saved), timeout=8000)


def handle_action(path, action):
    """What the notification buttons do (also used by the card)."""
    if action == "default":
        ask_app("card", path)
    elif action == "edit":
        edit(path)
    elif action == "text":
        ocr_to_clipboard(path, notify_result=True)
    elif action == "folder":
        show_in_folder(path)
    elif action == "delete":
        trash(path)
    elif action == "save":
        save_copy(path)
    elif action == "open":
        open_file(path)


# ------------------------------------------------------------------ file actions
def edit(path):
    """Arrows, text, highlight, blur: swappy. It writes the result back to
    the same file when its window is closed."""
    if not shutil.which("swappy"):
        notify(tr("The image editor is not installed."))
        return False
    _swappy_config()
    from system import spawn
    os.environ["ZETA_SCREENSHOTS_DIR"] = screenshots_dir()
    return spawn(["swappy", "-f", path, "-o", path])


def _swappy_config():
    """swappy's own Save button writes to its save_dir (the Desktop by
    default): point it to the Screenshots folder, once, without touching a
    configuration the user already has."""
    path = os.path.expanduser("~/.config/swappy/config")
    if os.path.exists(path):
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            # swappy expands save_dir with wordexp(): quoted (a folder name
            # with spaces stays one word) and with a fallback, so swappy
            # started from elsewhere (variable unset) still has a folder
            f.write("[Default]\nsave_dir=\"${ZETA_SCREENSHOTS_DIR:-$HOME/Pictures}\"\n"
                    "save_filename_format=Screenshot %Y-%m-%d %H-%M-%S edited.png\n"
                    "paint_mode=arrow\nearly_exit=false\n")
    except OSError:
        pass


def show_in_folder(path):
    """The file manager on the folder, with the file selected."""
    uri = "file://" + urllib.parse.quote(os.path.abspath(path))
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
                            "--object-path", "/org/freedesktop/FileManager1",
                            "--method", "org.freedesktop.FileManager1.ShowItems",
                            "[%s]" % gvariant_string(uri), "''"],
                           stdout=DEVNULL, stderr=DEVNULL, timeout=10)
        if r.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    from system import spawn
    return spawn(["xdg-open", os.path.dirname(os.path.abspath(path))])


def open_file(path):
    from system import spawn
    return spawn(["gio", "open", path])


def trash(path):
    """"Delete" moves to the Trash: a capture deleted by mistake comes back."""
    try:
        r = subprocess.run(["gio", "trash", "--", path], stdout=DEVNULL, stderr=DEVNULL, timeout=15)
        ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    if not ok and not is_saved(path):
        discard(path)
        ok = True
    return ok


def save_copy(path):
    """Save a capture that was only copied to the clipboard."""
    dest = unique_path(ensure_folder(screenshots_dir()), SCREENSHOT_STEM, ".png")
    try:
        shutil.copyfile(path, dest)
    except OSError:
        discard(dest)
        return None
    return dest


def thumbnail(path):
    """Image of a capture for the notification and the card (a frame of the
    video for recordings)."""
    if path.lower().endswith(".png"):
        return path
    digest = hashlib.sha1(os.path.abspath(path).encode()).hexdigest()[:16]
    thumb = os.path.join(runtime_dir(), "thumb-%s.png" % digest)
    if os.path.exists(thumb):
        return thumb
    try:
        subprocess.run(["ffmpegthumbnailer", "-i", path, "-o", thumb, "-s", "480", "-t", "10%"],
                       stdout=DEVNULL, stderr=DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return thumb if os.path.exists(thumb) else None


# ------------------------------------------------------------------ text (OCR)
def _upscaled_for_ocr(path):
    """Screen text is small: tesseract reads it much better at twice the
    size (zeta-text-capture captures at scale 2 for the same reason)."""
    size = png_size(path)
    tool = shutil.which("magick") or shutil.which("convert")
    if not size or not tool or size[0] * size[1] > 4_000_000:
        return None
    fd, out = tempfile.mkstemp(prefix="zeta-ocr-", suffix=".png", dir=runtime_dir())
    os.close(fd)
    try:
        r = subprocess.run(["nice", "-n", "10", tool, path, "-resize", "200%", out],
                           stdout=DEVNULL, stderr=DEVNULL, timeout=60)
        if r.returncode == 0 and os.path.getsize(out) > 0:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    discard(out)
    return None


def ocr_text(path):
    """Text in the image, in the session language and English (None = error)."""
    if not shutil.which("tesseract"):
        return None
    from system import ocr
    big = _upscaled_for_ocr(path)
    env = dict(os.environ, OMP_THREAD_LIMIT="2")
    try:
        r = subprocess.run(["nice", "-n", "10", "tesseract", big or path, "stdout",
                            "-l", ocr.languages(), "--psm", "3"],
                           capture_output=True, text=True, timeout=180, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if big:
            discard(big)
    return r.stdout.strip() if r.returncode == 0 else None


def ocr_to_clipboard(path, notify_result=False):
    """(ok, text). ok is False when there is no text or recognition failed."""
    text = ocr_text(path)
    ok = bool(text) and copy_text(text)
    if notify_result:
        if text is None:
            notify(tr("Text recognition is not available."))
        elif not text:
            notify(tr("No readable text found."))
        else:
            preview = text if len(text) <= 160 else text[:157].rstrip() + "…"
            notify(tr("Text copied to the clipboard"), preview)
    return ok, text or ""


# ------------------------------------------------------------------ color picker
def pick_color():
    """#RRGGBB under the pointer (hyprpicker), copied. None = canceled."""
    if not shutil.which("hyprpicker"):
        notify(tr("The color picker is not installed."))
        return None
    # no "-q": in hyprpicker 0.4.7 it also silences the color itself (it is
    # printed at the "NONE" log level); its other log lines start with "["
    try:
        r = subprocess.run(["hyprpicker", "-f", "hex", "-b"], capture_output=True, text=True,
                           timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    colors = [ln.strip() for ln in r.stdout.splitlines()
              if len(ln.strip()) == 7 and ln.strip().startswith("#")]
    color = colors[-1] if colors else ""
    if r.returncode != 0 or not color:
        return None
    copy_text(color)
    swatch = os.path.join(runtime_dir(), "color.svg")
    try:
        with open(swatch, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
                    '<rect x="2" y="2" width="60" height="60" rx="14" fill="%s" '
                    'stroke="#FFFFFF" stroke-opacity="0.3"/></svg>' % color)
    except OSError:
        swatch = None
    notify(tr("Color {color} copied").format(color=color), icon=swatch)
    return color


# ------------------------------------------------------------------ recording
def _state_path():
    return os.path.join(runtime_dir(), "recording.json")


# /proc/PID/comm of the background child of "zeta-screenshot record"
# (the name of the script, cut at 15 characters, or the interpreter)
SUPERVISOR_NAMES = ("zeta-screenshot", "python3")


def _comm(pid):
    try:
        with open("/proc/%d/comm" % pid) as f:
            return f.read().strip()
    except (OSError, ValueError, TypeError):
        return ""


def _alive(pid):
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    # a zombie still answers kill(0): it is no longer recording
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def recording_state():
    """The running recording (dict) or None. A stale state (wf-recorder no
    longer running, e.g. after a crash) is removed."""
    try:
        with open(_state_path()) as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(st, dict):
        discard(_state_path())
        return None
    pid = st.get("pid")
    if isinstance(pid, int) and _alive(pid) and _comm(pid) == "wf-recorder":
        return st
    # wf-recorder has ended: its supervisor removes the state within a
    # second and tells the user; only a state left behind is removed here.
    sup = st.get("supervisor")
    if not (isinstance(sup, int) and _alive(sup) and _comm(sup) in SUPERVISOR_NAMES):
        discard(_state_path())
    return None


def _write_state(st):
    tmp = _state_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, _state_path())


def status():
    st = recording_state()
    if not st:
        return {"recording": False, "file": None}
    return {"recording": True, "file": st.get("file"), "started": st.get("started"),
            "elapsed": int(time.time() - st.get("started", time.time())),
            "audio": bool(st.get("audio")), "target": st.get("target"),
            "stopping": bool(st.get("stopping"))}


def free_bytes(path):
    p = os.path.abspath(path)
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    try:
        s = os.statvfs(p or "/")
    except OSError:
        return 1 << 62
    return s.f_bavail * s.f_frsize


def recorder_command(dest, geometry_text=None, output=None, audio=False):
    """wf-recorder: H.264 (x264 "ultrafast", wf-recorder's default, the
    lightest on a small CPU) in yuv420p for any player; the cursor is
    always drawn. Sound: the monitor of the default output (what the
    computer plays), through PipeWire's PulseAudio server."""
    cmd = ["wf-recorder", "-y", "-f", dest]
    if geometry_text:
        cmd += ["-g", geometry_text]
    elif output:
        cmd += ["-o", output]
    if audio:
        cmd += ["--audio-backend=pulse", "--audio=@DEFAULT_MONITOR@"]
    return cmd


def pill_corner(rect, output, monitors, size=(190, 44), margin=12):
    """Where the recording indicator goes, so that it is not recorded:
    (monitor name, corner) with corner in top-right, top-left,
    bottom-right, bottom-left. rect is the recorded area (x, y, w, h), or
    None when the whole screen named `output` is recorded: then another
    screen is used if there is one (with a single screen the indicator
    stays in the top-right corner and is part of the video)."""
    if rect is None:
        # whole screen: another screen if there is one
        others = [m for m in monitors if m["name"] != output]
        if others:
            return others[0]["name"], "top-right"
        target = next((m for m in monitors if m["name"] == output), monitors[0] if monitors else None)
        return (target["name"] if target else None), "top-right"
    x, y, w, h = rect
    target = monitor_at(monitors, x, y) if monitors else None
    if target is None:
        return None, "top-right"
    pw, ph = size
    mx, my, mw, mh = target["x"], target["y"], target["w"], target["h"]
    corners = {
        "top-right": (mx + mw - margin - pw, my + margin),
        "top-left": (mx + margin, my + margin),
        "bottom-right": (mx + mw - margin - pw, my + mh - margin - ph - 64),
        "bottom-left": (mx + margin, my + mh - margin - ph - 64),
    }
    for name in ("top-right", "top-left", "bottom-right", "bottom-left"):
        cx, cy = corners[name]
        if cx + pw <= x or cx >= x + w or cy + ph <= y or cy >= y + h:
            return target["name"], name
    others = [m for m in monitors if m["name"] != target["name"]]
    if others:
        return others[0]["name"], "top-right"
    return target["name"], "top-right"


def _log_tail(path):
    try:
        with open(path, errors="replace") as f:
            lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
    except OSError:
        return ""
    return lines[-1] if lines else ""


def start_recording(target=None, audio=False, delay=0):
    """Start a recording (call it in a background child, which then stays
    as its supervisor). target: "region" (drag an area), "screen" (the
    screen under the pointer) or None (click a screen or drag an area).
    Returns (file, error); (None, None) = canceled. A second request while
    one is choosing its area is ignored (the shortcut pressed twice)."""
    import fcntl
    lock = os.open(os.path.join(runtime_dir(), "record.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock)
        return None, None
    try:
        return _start_recording(target, audio, delay)
    finally:
        os.close(lock)


def _start_recording(target, audio, delay):
    if recording_state():
        return None, tr("A recording is already running.")
    if not shutil.which("wf-recorder"):
        return None, tr("The screen recorder is not installed.")
    folder = recordings_dir()
    if free_bytes(folder) < FREE_SPACE_MIN:
        return None, tr("Not enough free space to record (at least 1 GB is needed).")
    wait(delay)
    geometry_text = output = None
    region = None
    if target == "screen":
        m = monitor_under_pointer()
        output = m["name"] if m else None
    else:
        geometry_text = select_region() if target == "region" else select_for_recording()
        if geometry_text is None:
            return None, None
        region = parse_geometry(geometry_text)
        mons = monitor_rects()
        # wf-recorder records one screen: an area across two screens is cut
        # to the screen where it starts (it would record the whole screen)
        m = monitor_at(mons, region[0], region[1]) if mons else None
        if m:
            x1, y1 = max(region[0], m["x"]), max(region[1], m["y"])
            x2 = min(region[0] + region[2], m["x"] + m["w"])
            y2 = min(region[1] + region[3], m["y"] + m["h"])
            if x2 - x1 >= 2 and y2 - y1 >= 2:
                region = (x1, y1, x2 - x1, y2 - y1)
                geometry_text = geometry(region)
        # a click on a whole screen: record that screen by name
        for m in mons:
            if region == (m["x"], m["y"], m["w"], m["h"]):
                geometry_text, output, region = None, m["name"], None
                break
    ensure_folder(folder)
    dest = unique_path(folder, RECORDING_STEM, ".mp4")
    log = os.path.join(runtime_dir(), "recording.log")
    proc = None
    for with_audio in ((True, False) if audio else (False,)):
        with open(log, "w") as lf:
            try:
                proc = subprocess.Popen(recorder_command(dest, geometry_text, output, with_audio),
                                        stdin=DEVNULL, stdout=lf, stderr=lf, start_new_session=True)
            except OSError as e:
                discard(dest)
                return None, str(e)
        started = time.time()
        # a wrong option or a missing sound server ends it within a second
        for _ in range(15):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        if proc.poll() is None:
            audio_failed = audio and not with_audio
            break
    else:
        discard(dest)
        return None, _log_tail(log) or tr("The screen recorder did not start.")
    _write_state({"pid": proc.pid, "supervisor": os.getpid(), "file": dest, "started": started,
                  "audio": audio and not audio_failed, "target": "screen" if output else "region",
                  "region": list(region) if region else None, "output": output})
    if audio_failed:
        notify(tr("Recording without sound"), tr("The computer sound could not be recorded."))
    ask_app("indicator")
    return dest, None


def supervise():
    """Wait for the running recording to end (stop button, shortcut, full
    disk), then tell the user. Runs in the background child that started it."""
    st = recording_state()
    if not st:
        return
    pid, dest = st["pid"], st["file"]
    folder = os.path.dirname(dest)
    reason = None
    stopping = None
    while True:
        try:
            done, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            done = pid
        if done:
            break
        if stopping is None and free_bytes(folder) < FREE_SPACE_MIN:
            reason = "disk"
            stopping = time.time()
            _signal(pid, signal.SIGINT)
        elif stopping is not None and time.time() - stopping > 20:
            _signal(pid, signal.SIGKILL)
        time.sleep(1)
    duration = int(time.time() - st.get("started", time.time()))
    discard(_state_path())
    ask_app("indicator", start=False)          # hides it (it checks the state every second anyway)
    if not os.path.exists(dest) or os.path.getsize(dest) == 0:
        discard(dest)
        notify(tr("The recording could not be saved."),
               _log_tail(os.path.join(runtime_dir(), "recording.log")))
        return
    if reason == "disk":
        summary = tr("Recording stopped: less than 1 GB of free space left")
    else:
        summary = tr("Screen recording saved")
    body = "%s · %s" % (os.path.basename(dest), format_duration(duration))
    action = notify(summary, body, icon=thumbnail(dest),
                    actions=[("default", tr("Open")), ("open", tr("Play")),
                             ("folder", tr("Open Folder"))], timeout=10000)
    if action:
        handle_action(dest, action)


def _signal(pid, sig):
    try:
        os.kill(pid, sig)
    except OSError:
        pass


def stop_recording(wait=True, timeout=25):
    """Ask wf-recorder to finish the file (SIGINT). True if one was running."""
    st = recording_state()
    if not st:
        return False
    st["stopping"] = time.time()
    try:
        _write_state(st)
    except OSError:
        pass
    _signal(st["pid"], signal.SIGINT)
    if not wait:
        return True
    end = time.time() + timeout
    while time.time() < end and _alive(st["pid"]):
        time.sleep(0.1)
    return True


def format_duration(seconds):
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)
