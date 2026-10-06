# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — gestione delle finestre (Hyprland).

Hyprland non ha la "riduzione a icona": qui la realizziamo spostando la
finestra in uno spazio speciale nascosto e ricordando da dove veniva, così il
pulsante «riduci» della barra del titolo fa davvero qualcosa e la finestra si
può riaprire dalla barra in basso.
"""
import json
import os
import signal
import subprocess
import time

HIDDEN = "special:zetamin"
STATE = os.path.expanduser("~/.cache/zeta/finestre.json")


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
    """Esegue un dispatcher di Hyprland 0.55 (formato Lua). True se riuscito."""
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
    """Aggiorna subito il contatore nella barra (SIGRTMIN+9)."""
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


# ---------------------------------------------------------------- anteprime
# Le finestre ridotte compaiono nella barra come miniature (come nel Dock di
# macOS), non come «1 ridotta». L'immagine si cattura un attimo prima di
# nasconderla, quando e' ancora sullo schermo: dopo non e' piu' disegnata.
ANTEPRIME = os.path.expanduser("~/.cache/zeta/ridotte")
POSTI = 8                                  # miniature al massimo nella barra
RAPPORTO = 1.6                             # larghezza / altezza della miniatura


BARRA_TITOLO = 32                          # hyprbars (bar_height in hyprland.lua)


def rettangolo(win):
    """(x, y, l, a) della finestra come si vede, barra del titolo compresa
    (Hyprland la disegna sopra le coordinate della finestra; a schermo intero
    non c'e')."""
    try:
        (x, y), (w, h) = win["at"], win["size"]
    except (KeyError, TypeError, ValueError):
        return None
    if not win.get("fullscreen") and y >= BARRA_TITOLO:
        y, h = y - BARRA_TITOLO, h + BARRA_TITOLO
    return (x, y, w, h)


def cattura(win, dest):
    """Immagine della finestra (deve essere visibile). Il rettangolo usato,
    oppure None."""
    r = rettangolo(win)
    if not r or r[2] < 8 or r[3] < 8:
        return None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        p = subprocess.run(["grim", "-l", "0", "-g", "%d,%d %dx%d" % r, dest],
                           capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r if p.returncode == 0 and os.path.exists(dest) else None


def _icona_app(classe):
    try:
        import sys
        if "/usr/lib/zeta" not in sys.path:
            sys.path.insert(0, "/usr/lib/zeta")
        from system import applicazioni
        c = (classe or "").lower()
        for a in applicazioni.tutte():
            nomi = {a.wm_class.lower(), a.id[:-8].lower(), os.path.basename(a.eseguibile).lower()}
            if c and c in nomi and a.icona:
                p = applicazioni.icona_file(a.icona)
                return p if os.path.exists(p) else None
    except Exception:  # noqa: BLE001 - senza icona la miniatura resta valida
        return None
    return None


def componi_anteprima(cattura_png, dest, classe="", altezza=84):
    """Miniatura arrotondata con l'icona dell'app nell'angolo (PNG, 2x)."""
    import cairo
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, GdkPixbuf
    W, H = int(altezza * RAPPORTO), altezza
    sup = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(sup)

    def rett(x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -1.5708, 0)
        cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
        cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
        cr.arc(x + r, y + r, r, 3.1416, 4.7124)
        cr.close_path()
    m = 3
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(cattura_png)
        sc = min((W - 2 * m) / pb.get_width(), (H - 2 * m) / pb.get_height())
        pw, ph = max(1, int(pb.get_width() * sc)), max(1, int(pb.get_height() * sc))
        pb = pb.scale_simple(pw, ph, GdkPixbuf.InterpType.BILINEAR)
    except Exception:  # noqa: BLE001
        pb, pw, ph = None, W - 2 * m, H - 2 * m
    ox, oy = (W - pw) / 2, (H - ph) / 2
    cr.save()
    rett(ox, oy, pw, ph, 7)
    cr.clip()
    if pb is not None:
        Gdk.cairo_set_source_pixbuf(cr, pb, ox, oy)
    else:
        cr.set_source_rgb(0.12, 0.12, 0.13)
    cr.paint()
    cr.restore()
    rett(ox + 0.5, oy + 0.5, pw - 1, ph - 1, 7)
    cr.set_source_rgba(1, 1, 1, 0.18)
    cr.set_line_width(1)
    cr.stroke()
    icona = _icona_app(classe)
    if icona:
        try:
            lato = int(H * 0.46)
            ib = GdkPixbuf.Pixbuf.new_from_file_at_size(icona, lato, lato)
            Gdk.cairo_set_source_pixbuf(cr, ib, W - ib.get_width() - 1, H - ib.get_height() - 1)
            cr.paint()
        except Exception:  # noqa: BLE001
            pass
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp.png"
    sup.write_to_png(tmp)
    os.replace(tmp, dest)
    return dest


def _nome_file(addr, tipo):
    return os.path.join(ANTEPRIME, "%s-%s.png" % (addr.replace("0x", ""), tipo))


def togli_anteprima(addr):
    for tipo in ("mini", "grande"):
        try:
            os.unlink(_nome_file(addr, tipo))
        except OSError:
            pass


def ridotte_in_ordine():
    """Le finestre ridotte, nell'ordine della barra, solo dal file di stato
    (niente hyprctl: la barra lo legge a ogni aggiornamento)."""
    return list(_load().items())


def dimentica(addr):
    """Una finestra ridotta non c'e' piu' (chiusa): via dallo stato e dalla barra."""
    togli_anteprima(addr)
    state = _load()
    if addr in state:
        state.pop(addr, None)
        _save(state)


def minimize(addr=None):
    """Nasconde la finestra (attiva se addr è None). True se fatto."""
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
        return False                      # già nascosta
    state = _load()
    state[addr] = {"workspace": ws or "1",
                   "title": win.get("title") or "",
                   "class": win.get("class") or "",
                   "rect": rettangolo(win)}
    _save(state)
    ok = dispatch('hl.dsp.window.move({ workspace = "%s", follow = false, window = "%s" })'
                  % (HIDDEN, _sel(addr)))
    if not ok:
        state.pop(addr, None)
        _save(state)
    return ok


def minimized():
    """Elenco delle finestre ridotte ancora esistenti (le altre vengono tolte)."""
    state = _load()
    if not state:
        return []
    live = {c.get("address"): c for c in clients()}
    out, changed = [], False
    for addr, info in list(state.items()):
        c = live.get(addr)
        if c is None:
            state.pop(addr, None)
            togli_anteprima(addr)
            changed = True
            continue
        if not str((c.get("workspace") or {}).get("name", "")).startswith("special:"):
            # l'utente l'ha riportata fuori in altro modo
            state.pop(addr, None)
            togli_anteprima(addr)
            changed = True
            continue
        out.append({"address": addr,
                    "title": c.get("title") or info.get("title") or "Finestra",
                    "class": c.get("class") or info.get("class") or "",
                    "workspace": info.get("workspace") or "1"})
    if changed:
        _save(state)
    return out


def restore(addr):
    """Riporta la finestra nel suo spazio di lavoro e le dà il fuoco."""
    state = _load()
    ws = (state.get(addr) or {}).get("workspace") or "1"
    ok = dispatch('hl.dsp.window.move({ workspace = "%s", follow = false, window = "%s" })'
                  % (ws, _sel(addr)))
    if ok:
        togli_anteprima(addr)            # prima di avvisare la barra
        state.pop(addr, None)
        _save(state)
        dispatch('hl.dsp.focus({ workspace = "%s" })' % ws)
        dispatch('hl.dsp.focus({ window = "%s" })' % _sel(addr))
    return ok


def focus(addr):
    return dispatch('hl.dsp.focus({ window = "%s" })' % _sel(addr))


def close(addr=None):
    if addr is None:
        return dispatch("hl.dsp.window.close()")
    return dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(addr))


def toggle_maximize(addr=None):
    tgt = ", window = \"%s\"" % _sel(addr) if addr else ""
    return dispatch('hl.dsp.window.fullscreen({ mode = "maximized"%s })' % tgt)


def open_windows():
    """Finestre visibili (non ridotte), dalla più recente."""
    out = []
    for c in clients():
        ws = str((c.get("workspace") or {}).get("name", ""))
        if ws.startswith("special:"):
            continue
        out.append({"address": c.get("address"), "title": c.get("title") or "Finestra",
                    "class": c.get("class") or "", "workspace": ws,
                    "pid": c.get("pid") or 0})
    out.sort(key=lambda w: w["workspace"])
    return out


def memoria_mb(pid):
    """Quanta memoria occupa un processo, in MB (0 se non si riesce a leggere)."""
    try:
        with open("/proc/%d/statm" % int(pid)) as f:
            pagine = int(f.read().split()[1])
        return pagine * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        return 0.0


def bloccato_su_disco(pid):
    """Vero se il processo e' fermo in attesa del disco o di un driver.

    E' lo stato «D»: il processo non risponde e non si puo' nemmeno
    interrompere finche' il kernel non gli restituisce cio' che aspetta. E'
    l'unico «non risponde» che si possa affermare guardando il sistema, e per
    questo e' l'unico che viene mostrato: inventare una diagnosi peggiorerebbe
    le cose invece di aiutare.
    """
    try:
        with open("/proc/%d/stat" % int(pid)) as f:
            campi = f.read().rsplit(")", 1)[1].split()
        return campi[0] == "D"
    except (OSError, ValueError, IndexError):
        return False


# Pezzi del desktop che non si terminano mai da qui: fermarli significherebbe
# perdere la sessione intera, il rimedio sarebbe peggio del male.
PROTETTI = {"Hyprland", "Xwayland", "waybar", "mako", "swaybg", "zeta-session",
            "zeta-vigila", "systemd", "dbus-daemon", "dbus-broker", "sddm",
            "sddm-helper", "pipewire", "pipewire-pulse", "wireplumber",
            "xdg-desktop-por", "xdg-document-po", "xdg-permission-", "polkit-mate-aut",
            "gnome-keyring-d", "sshd", "sshd-session", "login", "agetty"}


def _comm(pid):
    try:
        with open("/proc/%d/comm" % pid) as f:
            return f.read().strip()
    except OSError:
        return ""


def _figli_diretti():
    """ppid -> [pid] per tutti i processi, letto da /proc in un colpo solo."""
    mappa = {}
    for voce in os.listdir("/proc"):
        if not voce.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % voce) as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        mappa.setdefault(ppid, []).append(int(voce))
    return mappa


def albero(pid):
    """Il processo e tutti i suoi discendenti dello stesso utente.

    Un programma spesso ne lancia altri (Firefox i suoi processi per le
    schede, il terminale il comando che ci gira dentro): terminare solo il
    primo lasciava vivi gli altri, e il blocco restava.
    """
    mio = os.getuid()
    mappa = _figli_diretti()
    visti, coda = [], [pid]
    while coda:
        p = coda.pop()
        if p in visti:
            continue
        try:
            if os.stat("/proc/%d" % p).st_uid != mio:
                continue
        except OSError:
            continue
        visti.append(p)
        coda.extend(mappa.get(p, []))
    return visti


def protetto(pid):
    return int(pid) <= 1 or int(pid) == os.getpid() or _comm(int(pid)) in PROTETTI


def _vivo(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # uno zombie e' gia' morto: aspetta solo che il padre lo raccolga
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def force_quit(pid, attesa=3.0, forza=True):
    """Termina un programma piantato, con i suoi processi figli: prima con
    garbo, poi per forza.

    Si manda TERM e si aspetta: un programma che risponde ancora salva e se ne
    va da solo. Se dopo qualche secondo e' ancora li' vuol dire che non
    risponde davvero, e allora KILL. Partire subito con KILL farebbe perdere
    il lavoro non salvato anche a chi si sarebbe chiuso da solo.
    Con forza=False ci si ferma a TERM: e' la chiusura normale («chiudi»),
    che non deve mai diventare d'autorita' senza che l'utente lo chieda.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False, "Processo non valido."
    if protetto(pid):
        return False, "Questo processo fa parte del desktop e non si termina da qui."
    tutti = [p for p in albero(pid) if not protetto(p)]
    if not tutti:
        if not _vivo(pid):
            return True, "Era gia' terminato."
        return False, "Serve un permesso che non hai per terminare questo processo."
    # prima il principale (puo' chiudere lui i figli in ordine), poi gli altri
    for p in tutti:
        try:
            os.kill(p, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    scaduto = time.monotonic() + attesa
    while time.monotonic() < scaduto and any(_vivo(p) for p in tutti):
        time.sleep(0.15)
    rimasti = [p for p in tutti if _vivo(p)]
    if not rimasti:
        return True, "Chiuso" + (" (con %d processi collegati)." % (len(tutti) - 1)
                                 if len(tutti) > 1 else ".")
    if not forza:
        return False, "Non si e' chiuso da solo."
    for p in rimasti:
        try:
            os.kill(p, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    fine = time.monotonic() + 2.0
    while time.monotonic() < fine and any(_vivo(p) for p in rimasti):
        time.sleep(0.1)
    ancora = [p for p in rimasti if _vivo(p)]
    if not ancora:
        return True, "Terminato forzatamente" + (" (con %d processi collegati)." % (len(tutti) - 1)
                                                if len(tutti) > 1 else ".")
    if any(bloccato_su_disco(p) for p in ancora):
        return False, ("Il processo non risponde nemmeno a una terminazione forzata: "
                       "e' bloccato dal kernel in attesa del disco. Si chiudera' "
                       "appena il disco risponde.")
    return False, "Non e' stato possibile terminarlo."


def finestra_al_punto(x, y):
    """La finestra visibile che sta sotto il punto (x, y) dello schermo.

    Se piu' finestre si sovrappongono vince quella usata per ultima, che e'
    quella davanti. Solo le finestre dello spazio di lavoro mostrato.
    """
    monitor = _hyprctl(["monitors"], as_json=True) or []
    attivi = {m.get("activeWorkspace", {}).get("id") for m in monitor}
    attivi |= {m.get("specialWorkspace", {}).get("id") for m in monitor
               if m.get("specialWorkspace", {}).get("id")}
    candidati = []
    for c in clients():
        if not c.get("mapped", True) or c.get("hidden"):
            continue
        if (c.get("workspace") or {}).get("id") not in attivi and not c.get("pinned"):
            continue
        (cx, cy), (w, h) = c.get("at", (0, 0)), c.get("size", (0, 0))
        if cx <= x < cx + w and cy <= y < cy + h:
            candidati.append(c)
    if not candidati:
        return None
    return min(candidati, key=lambda c: c.get("focusHistoryID", 999))


def processi_pesanti(soglia_mb=250):
    """Processi dell'utente senza finestra che occupano molta memoria: una
    finestra piantata non e' l'unico modo in cui un programma blocca il
    computer."""
    con_finestra = {c.get("pid") for c in clients()}
    mio = os.getuid()
    out = []
    for voce in os.listdir("/proc"):
        if not voce.isdigit():
            continue
        pid = int(voce)
        try:
            if os.stat("/proc/%d" % pid).st_uid != mio:
                continue
        except OSError:
            continue
        if pid in con_finestra or protetto(pid):
            continue
        mb = memoria_mb(pid)
        if mb >= soglia_mb:
            out.append({"pid": pid, "nome": _comm(pid), "mb": mb})
    out.sort(key=lambda d: -d["mb"])
    return out[:8]
