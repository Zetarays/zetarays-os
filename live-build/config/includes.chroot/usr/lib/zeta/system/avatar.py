# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — l'immagine dell'utente (avatar).

Una sola immagine, tonda, 512x512 con lo sfondo trasparente: ~/.face (il nome
standard, con ~/.face.icon accanto), la stessa che AccountsService da' alla
schermata di accesso (SDDM non puo' leggere la cartella personale). Si vede
nel menu di energia e account, sulla schermata di blocco e all'accesso.

Due possibilita':
- una foto scelta dall'utente (.jpg o .png): si ritaglia al centro in un
  quadrato, si riduce a 512 px con un filtro di qualita' e si taglia in tondo;
- un cerchio pieno in uno dei quattro colori d'accento del sistema (la
  tavolozza di ui/accento.py, l'unica), senza disegni. Di serie e' il colore
  d'accento scelto e lo segue quando cambia (zeta-accent chiama
  segui_accento); scelto un colore preciso, resta quello.

La scelta sta in ~/.config/zeta/avatar: «accento», «#RRGGBB» o «foto».
"""
import math
import os
import tempfile

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib  # noqa: E402

from i18n import tr  # noqa: E402
from ui import accento  # noqa: E402

HOME = os.path.expanduser("~")
FACE = os.path.join(HOME, ".face")
FACE_ICON = os.path.join(HOME, ".face.icon")
SCELTA = os.path.join(HOME, ".config", "zeta", "avatar")
LATO = 512
ESTENSIONI = (".png", ".jpg", ".jpeg")


def percorso():
    """L'immagine da mostrare (creata se manca)."""
    if not os.path.isfile(FACE):
        assicura(accounts=False)
    return FACE


def scelta():
    """«accento», «foto» o un colore «#RRGGBB» della tavolozza."""
    try:
        with open(SCELTA) as f:
            v = f.read().strip()
    except OSError:
        # una ~/.face messa dall'utente prima di questa versione e' sua
        return "foto" if os.path.isfile(FACE) else "accento"
    if v in ("accento", "foto"):
        return v
    v = v.upper()
    if any(c == v for _k, c, _n in accento.TAVOLOZZA):
        return v
    return "accento"


def _salva_scelta(valore):
    os.makedirs(os.path.dirname(SCELTA), exist_ok=True)
    tmp = SCELTA + ".tmp"
    with open(tmp, "w") as f:
        f.write(valore + "\n")
    os.replace(tmp, SCELTA)


def personale():
    """Vero se l'utente ha scelto una foto sua."""
    return scelta() == "foto" and os.path.isfile(FACE)


def colore_attuale():
    """Il colore del cerchio (anche quando segue l'accento)."""
    s = scelta()
    if s == "accento":
        c = accento.scelto_hex()
        # un colore personalizzato fuori tavolozza va bene lo stesso
        return c
    return s if s.startswith("#") else accento.scelto_hex()


def _cerchio(colore):
    """PNG 512x512: cerchio pieno del colore, fondo trasparente. Il bianco ha
    un filo grigio appena visibile, per non sparire su un fondo chiaro."""
    import cairo
    h = colore.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    superficie = cairo.ImageSurface(cairo.FORMAT_ARGB32, LATO, LATO)
    cr = cairo.Context(superficie)
    cr.arc(LATO / 2, LATO / 2, LATO / 2, 0, 2 * math.pi)
    cr.set_source_rgb(r, g, b)
    cr.fill()
    if 0.299 * r + 0.587 * g + 0.114 * b > 0.85:
        cr.arc(LATO / 2, LATO / 2, LATO / 2 - 4, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.16)
        cr.set_line_width(8)
        cr.stroke()
    fd, tmp = tempfile.mkstemp(prefix=".face-", suffix=".png", dir=HOME)
    os.close(fd)
    superficie.write_to_png(tmp)
    return tmp


def _tonda(pixbuf):
    """Pixbuf quadrato -> PNG tondo (bordo smussato) in un file temporaneo."""
    import io
    import cairo
    lato = pixbuf.get_width()
    ok, dati = pixbuf.save_to_bufferv("png", [], [])
    foto = cairo.ImageSurface.create_from_png(io.BytesIO(dati))
    superficie = cairo.ImageSurface(cairo.FORMAT_ARGB32, lato, lato)
    cr = cairo.Context(superficie)
    cr.arc(lato / 2, lato / 2, lato / 2, 0, 2 * math.pi)
    cr.clip()
    cr.set_source_surface(foto, 0, 0)
    cr.paint()
    fd, tmp = tempfile.mkstemp(prefix=".face-", suffix=".png", dir=HOME)
    os.close(fd)
    superficie.write_to_png(tmp)
    return tmp


def _scrivi(tmp, accounts=True):
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


def imposta_da_file(sorgente):
    """Una foto dell'utente (.jpg o .png) come avatar. (ok, messaggio)."""
    if not sorgente.lower().endswith(ESTENSIONI) or not os.path.isfile(sorgente):
        return False, tr("Choose a .jpg or .png picture.")
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(sorgente)
        pb = pb.apply_embedded_orientation() or pb      # foto del telefono girate
    except GLib.Error as e:
        return False, tr("That picture can't be opened: {error}").format(error=e.message)
    w, h = pb.get_width(), pb.get_height()
    if min(w, h) < 64:
        return False, tr("That picture is too small: at least 64 x 64 pixels.")
    q = min(w, h)
    quadrato = pb.new_subpixbuf((w - q) // 2, (h - q) // 2, q, q)
    # grande: riduzione di qualita' (HYPER, niente scalini); piccola: un solo
    # ingrandimento morbido
    quadrato = quadrato.scale_simple(LATO, LATO, GdkPixbuf.InterpType.HYPER if q >= LATO
                                     else GdkPixbuf.InterpType.BILINEAR)
    try:
        _scrivi(_tonda(quadrato))
        _salva_scelta("foto")
    except (OSError, GLib.Error) as e:
        return False, tr("Couldn't save the picture: {error}").format(error=e)
    return True, tr("New picture set.")


def imposta_colore(colore, accounts=True):
    """Il cerchio di un colore della tavolozza, o «accento» per seguire il
    colore d'accento del sistema. (ok, messaggio)"""
    try:
        if colore == "accento":
            disegno = accento.scelto_hex()
        else:
            disegno = colore.upper()
            if not any(c == disegno for _k, c, _n in accento.TAVOLOZZA):
                return False, tr("Choose one of the colors.")
        _scrivi(_cerchio(disegno), accounts=accounts)
        _salva_scelta("accento" if colore == "accento" else disegno)
    except (OSError, ValueError) as e:
        return False, tr("Couldn't save the picture: {error}").format(error=e)
    return True, tr("New picture set.")


def segui_accento():
    """Chiamato da zeta-accent: il cerchio che segue l'accento cambia colore
    con lui. Una foto o un colore scelto apposta non si toccano."""
    if scelta() == "accento":
        imposta_colore("accento")


def assicura(accounts=True):
    """All'accesso: se non c'e' ancora un'immagine, il cerchio del colore
    d'accento, anche per la schermata di accesso. Non tocca una scelta fatta."""
    if not os.path.isfile(FACE):
        imposta_colore("accento", accounts=accounts)
    elif accounts and not _accounts_ha_icona():
        _accounts(FACE)


# ------------------------------------------------------------- AccountsService
def _utente_dbus():
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    r = bus.call_sync("org.freedesktop.Accounts", "/org/freedesktop/Accounts",
                      "org.freedesktop.Accounts", "FindUserById",
                      GLib.Variant("(x)", (os.getuid(),)), GLib.VariantType("(o)"),
                      Gio.DBusCallFlags.NONE, 3000, None)
    return bus, r.unpack()[0]


def _accounts(file_png):
    """L'immagine anche ad AccountsService, per la schermata di accesso.
    L'utente puo' cambiare la propria senza password (polkit)."""
    try:
        bus, percorso_utente = _utente_dbus()
        bus.call_sync("org.freedesktop.Accounts", percorso_utente,
                      "org.freedesktop.Accounts.User", "SetIconFile",
                      GLib.Variant("(s)", (file_png,)), None,
                      Gio.DBusCallFlags.NONE, 5000, None)
        return True
    except GLib.Error:
        return False


def _accounts_ha_icona():
    try:
        bus, percorso_utente = _utente_dbus()
        r = bus.call_sync("org.freedesktop.Accounts", percorso_utente,
                          "org.freedesktop.DBus.Properties", "Get",
                          GLib.Variant("(ss)", ("org.freedesktop.Accounts.User", "IconFile")),
                          GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 3000, None)
        icona = r.unpack()[0]
        return bool(icona) and os.path.isfile(icona)
    except GLib.Error:
        return True          # senza AccountsService non si insiste


def nome_completo():
    import pwd
    u = pwd.getpwuid(os.getuid())
    return (u.pw_gecos.split(",")[0] or u.pw_name).strip(), u.pw_name
