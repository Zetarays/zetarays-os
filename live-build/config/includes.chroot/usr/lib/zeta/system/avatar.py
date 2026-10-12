# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — the user's picture (avatar).

A single round 512x512 image with a transparent background: ~/.face (the
standard name, with ~/.face.icon next to it), the same one AccountsService
hands to the login screen (SDDM cannot read the home folder). It shows up in
the power and account menu, on the lock screen and at login.

Two options:
- a photo chosen by the user (.jpg or .png): it is cropped to a centered
  square, scaled down to 512 px with a high-quality filter and cut round;
- a solid circle in one of the system's four accent colors (the palette in
  ui/accent.py, the only one), with no drawing. By default it is the chosen
  accent color and follows it when it changes (zeta-accent calls
  follow_accent); once a specific color is chosen, it stays.

The choice is stored in ~/.config/zeta/avatar: «accent», «#RRGGBB» or «photo».
"""
import math
import os
import tempfile

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib  # noqa: E402

from i18n import tr  # noqa: E402
from ui import accent  # noqa: E402

HOME = os.path.expanduser("~")
FACE = os.path.join(HOME, ".face")
FACE_ICON = os.path.join(HOME, ".face.icon")
CHOICE = os.path.join(HOME, ".config", "zeta", "avatar")
SIDE = 512
EXTENSIONS = (".png", ".jpg", ".jpeg")


def path():
    """The image to show (created if missing)."""
    if not os.path.isfile(FACE):
        ensure(accounts=False)
    return FACE


def choice():
    """«accent», «photo» or a palette color «#RRGGBB»."""
    try:
        with open(CHOICE) as f:
            v = f.read().strip()
    except OSError:
        # a ~/.face placed by the user before this version is their own
        return "photo" if os.path.isfile(FACE) else "accent"
    if v in ("accent", "photo"):
        return v
    v = v.upper()
    if any(c == v for _k, c, _n in accent.PALETTE):
        return v
    return "accent"


def _save_choice(value):
    os.makedirs(os.path.dirname(CHOICE), exist_ok=True)
    tmp = CHOICE + ".tmp"
    with open(tmp, "w") as f:
        f.write(value + "\n")
    os.replace(tmp, CHOICE)


def custom():
    """True if the user chose their own photo."""
    return choice() == "photo" and os.path.isfile(FACE)


def current_color():
    """The circle color (also when it follows the accent)."""
    s = choice()
    if s == "accent":
        c = accent.chosen_hex()
        # a custom color outside the palette is fine too
        return c
    return s if s.startswith("#") else accent.chosen_hex()


def _circle(color):
    """PNG 512x512: solid circle of the color, transparent background. White
    gets a barely visible gray outline so it does not vanish on a light
    background."""
    import cairo
    h = color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIDE, SIDE)
    cr = cairo.Context(surface)
    cr.arc(SIDE / 2, SIDE / 2, SIDE / 2, 0, 2 * math.pi)
    cr.set_source_rgb(r, g, b)
    cr.fill()
    if 0.299 * r + 0.587 * g + 0.114 * b > 0.85:
        cr.arc(SIDE / 2, SIDE / 2, SIDE / 2 - 4, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.16)
        cr.set_line_width(8)
        cr.stroke()
    fd, tmp = tempfile.mkstemp(prefix=".face-", suffix=".png", dir=HOME)
    os.close(fd)
    surface.write_to_png(tmp)
    return tmp


def _round(pixbuf):
    """Square pixbuf -> round PNG (smooth edge) in a temporary file."""
    import io
    import cairo
    side = pixbuf.get_width()
    ok, data = pixbuf.save_to_bufferv("png", [], [])
    photo = cairo.ImageSurface.create_from_png(io.BytesIO(data))
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, side, side)
    cr = cairo.Context(surface)
    cr.arc(side / 2, side / 2, side / 2, 0, 2 * math.pi)
    cr.clip()
    cr.set_source_surface(photo, 0, 0)
    cr.paint()
    fd, tmp = tempfile.mkstemp(prefix=".face-", suffix=".png", dir=HOME)
    os.close(fd)
    surface.write_to_png(tmp)
    return tmp


def _write(tmp, accounts=True):
    os.chmod(tmp, 0o644)
    os.replace(tmp, FACE)
    try:
        if os.path.lexists(FACE_ICON):
            os.unlink(FACE_ICON)
        os.symlink(".face", FACE_ICON)
    except OSError:
        pass
    if accounts:
        _accounts(FACE)


def set_from_file(source):
    """A user photo (.jpg or .png) as the avatar. Returns (ok, message)."""
    if not source.lower().endswith(EXTENSIONS) or not os.path.isfile(source):
        return False, tr("Choose a .jpg or .png picture.")
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(source)
        pb = pb.apply_embedded_orientation() or pb      # rotated phone photos
    except GLib.Error as e:
        return False, tr("That picture can't be opened: {error}").format(error=e.message)
    w, h = pb.get_width(), pb.get_height()
    if min(w, h) < 64:
        return False, tr("That picture is too small: at least 64 x 64 pixels.")
    q = min(w, h)
    square = pb.new_subpixbuf((w - q) // 2, (h - q) // 2, q, q)
    # large: high-quality downscaling (HYPER, no jaggies); small: a single
    # smooth upscale
    square = square.scale_simple(SIDE, SIDE, GdkPixbuf.InterpType.HYPER if q >= SIDE
                                     else GdkPixbuf.InterpType.BILINEAR)
    try:
        _write(_round(square))
        _save_choice("photo")
    except (OSError, GLib.Error) as e:
        return False, tr("Couldn't save the picture: {error}").format(error=e)
    return True, tr("New picture set.")


def set_color(color, accounts=True):
    """A circle in a palette color, or «accent» to follow the system accent
    color. Returns (ok, message)."""
    try:
        if color == "accent":
            design = accent.chosen_hex()
        else:
            design = color.upper()
            if not any(c == design for _k, c, _n in accent.PALETTE):
                return False, tr("Choose one of the colors.")
        _write(_circle(design), accounts=accounts)
        _save_choice("accent" if color == "accent" else design)
    except (OSError, ValueError) as e:
        return False, tr("Couldn't save the picture: {error}").format(error=e)
    return True, tr("New picture set.")


def follow_accent():
    """Called by zeta-accent: the circle that follows the accent changes color
    with it. A photo or a deliberately chosen color is left alone."""
    if choice() == "accent":
        set_color("accent")


def ensure(accounts=True):
    """At login: if there is no image yet, the accent-color circle, for the
    login screen too. An existing choice is not touched."""
    if not os.path.isfile(FACE):
        set_color("accent", accounts=accounts)
    elif accounts and not _accounts_has_icon():
        _accounts(FACE)


# ------------------------------------------------------------- AccountsService
def _dbus_user():
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    r = bus.call_sync("org.freedesktop.Accounts", "/org/freedesktop/Accounts",
                      "org.freedesktop.Accounts", "FindUserById",
                      GLib.Variant("(x)", (os.getuid(),)), GLib.VariantType("(o)"),
                      Gio.DBusCallFlags.NONE, 3000, None)
    return bus, r.unpack()[0]


def _accounts(file_png):
    """Also hands the image to AccountsService, for the login screen.
    Users can change their own without a password (polkit)."""
    try:
        bus, user_path = _dbus_user()
        bus.call_sync("org.freedesktop.Accounts", user_path,
                      "org.freedesktop.Accounts.User", "SetIconFile",
                      GLib.Variant("(s)", (file_png,)), None,
                      Gio.DBusCallFlags.NONE, 5000, None)
        return True
    except GLib.Error:
        return False


def _accounts_has_icon():
    try:
        bus, user_path = _dbus_user()
        r = bus.call_sync("org.freedesktop.Accounts", user_path,
                          "org.freedesktop.DBus.Properties", "Get",
                          GLib.Variant("(ss)", ("org.freedesktop.Accounts.User", "IconFile")),
                          GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 3000, None)
        icon = r.unpack()[0]
        return bool(icon) and os.path.isfile(icon)
    except GLib.Error:
        return True          # without AccountsService, don't insist


def full_name():
    import pwd
    u = pwd.getpwuid(os.getuid())
    return (u.pw_gecos.split(",")[0] or u.pw_name).strip(), u.pw_name
