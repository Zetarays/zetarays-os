# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS: Software Update through PackageKit.

The interface never runs apt as root. PackageKit (a system service started
on demand over D-Bus) does the work: it takes the APT lock and waits for it,
checks the signatures, resolves the dependencies and asks for the
administrator password through PolicyKit (org.freedesktop.packagekit.*,
shown by the session's polkit agent). Checking for updates needs no password
for the active user (system-sources-refresh is "yes" for active sessions).

Every call is asynchronous on the GLib main loop: the Settings window never
blocks. The command line (zeta-update-reminder) and zeta-selftest use the
same functions inside run_sync().

PyGObject pitfall (packagekit 1.3.1, python3-gi 3.50, tested): call
get_package_array(), get_details_array() and get_update_detail_array() ONCE
per result and copy the values into Python objects immediately. A second
call on the same result, after another transaction, returned package ids
that were empty strings ("The package id's '' are not valid").

The ZETA RAYS components themselves are not Debian packages: they ship in
the image and are updated with new releases, not from here.
"""
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
import time

import gi
from gi.repository import Gio, GLib

from i18n import tr

try:
    gi.require_version("PackageKitGlib", "1.0")
    from gi.repository import PackageKitGlib as Pk
except (ImportError, ValueError):            # package missing: the page says so
    Pk = None

STATE_FILE = os.path.expanduser("~/.config/zeta/software-update.json")
APT_LISTS = "/var/lib/apt/lists"
APT_ARCHIVES = "/var/cache/apt/archives"
APT_HISTORY = "/var/log/apt/history.log"
REBOOT_FLAG = "/run/reboot-required"
LIVE_MEDIUM = "/run/live/medium"
CHECK_EVERY = 7 * 24 * 3600            # a check older than a week is stale
SPACE_MARGIN = 200 * 1024 * 1024       # dpkg needs room for unpacking and triggers
LOCK_RETRY = 5                         # seconds between two attempts while the APT lock is taken
LOCK_WAIT = 15 * 60                    # then give up and say so

# Updated packages that only take effect after a restart, even when the
# package does not say so (kernel, C library, init, D-Bus, the compositor).
RESTART_PACKAGES = re.compile(
    r"^(linux-image-.*|linux-base|linux-firmware|firmware-.*|intel-microcode|amd64-microcode|"
    r"libc6|libc-bin|systemd|systemd-sysv|libsystemd0|libsystemd-shared|udev|libudev1|dbus|"
    r"dbus-daemon|dbus-broker|libdbus-1-3|libssl3t64|openssl|hyprland|libaquamarine.*|"
    r"libhyprutils.*|libhyprlang.*|libhyprcursor.*|libhyprgraphics.*|mesa-.*|libgl1-mesa-dri|"
    r"libdrm2|xwayland|sddm|polkitd|cryptsetup.*|grub-.*|shim-.*)$")

# outcome kinds (stable keys for the UI and the tests; the text is separate)
OK = "ok"
NO_NETWORK = "no-network"
REPO_UNREACHABLE = "repo-unreachable"
DOWNLOAD_FAILED = "download-failed"
CONFLICT = "conflict"
BROKEN = "broken"
NO_SPACE = "no-space"
LOCKED = "locked"
NOT_AUTHORIZED = "not-authorized"
CANCELLED = "cancelled"
SIGNATURE = "signature"
INSTALL_FAILED = "install-failed"
UNAVAILABLE = "unavailable"
FAILED = "failed"

_NETWORK_HINTS = ("temporary failure resolving", "could not resolve", "network is unreachable",
                  "no route to host", "name or service not known", "connection timed out",
                  "could not connect", "failed to connect")


def available():
    """True when the PackageKit library is installed (gir1.2-packagekitglib-1.0)."""
    return Pk is not None


def is_live():
    """Running from the installation media: whatever is installed lives in RAM."""
    return os.path.exists(LIVE_MEDIUM)


# ----------------------------------------------------------------- data
class Update:
    """One available update, as plain Python values."""
    __slots__ = ("id", "name", "version", "arch", "origin", "summary", "security", "info",
                 "old_id", "old_version", "download_size", "size", "old_size")

    def __init__(self, package_id, info, summary):
        self.id = package_id
        parts = (package_id.split(";") + ["", "", "", ""])[:4]
        self.name, self.version, self.arch, self.origin = parts
        self.info = info                     # PackageKit info as text: security, normal, ...
        self.summary = summary or ""
        self.security = info == "security" or "security" in self.origin
        self.old_id = ""
        self.old_version = ""
        self.download_size = 0               # bytes; 0 = not reported
        self.size = 0                        # installed size of the new version
        self.old_size = 0                    # installed size of the current version

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


class Outcome:
    """Result of an operation: kind is a stable key, message is for people."""

    def __init__(self, kind=OK, message="", detail="", updates=None, restart=""):
        self.kind = kind
        self.message = message
        self.detail = detail                 # PackageKit/apt text, for "Details"
        self.updates = updates or []
        self.restart = restart               # "", "session" or "system"
        self.removals = []                   # names the update would remove (simulation)
        self.additions = []                  # new packages it would install
        self.held = []                       # held packages (apt-mark hold)
        self.extra = []                      # (download, installed size) of the additions
        self.broken = []                     # packages left half-installed (dpkg)

    @property
    def ok(self):
        return self.kind == OK

    def __repr__(self):
        return "Outcome(%s, %r, %d updates)" % (self.kind, self.message, len(self.updates))


def _bytes(n):
    """Sizes as PackageKit reports them: G_MAXUINT64 or negative = unknown."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return 0
    return n if 0 <= n < 2 ** 63 else 0


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1000.0
    return "%.1f GB" % n


# ----------------------------------------------------------------- errors
def _error_name(err):
    """PackageKit error enum name ("no-network", "dep-resolution-failed"...)
    from a GLib.Error raised by a PackageKit transaction, or "" for other errors.
    PackageKit encodes it as 0xff + PkErrorEnum in the pk-client-error domain
    (verified: no network gives code 319 = 0xff + 64, cannot-fetch-sources)."""
    if Pk is None or not isinstance(err, GLib.Error):
        return ""
    if err.domain != "pk-client-error-quark":
        return ""
    if err.code > 0xff:
        try:
            return Pk.error_enum_to_string(err.code - 0xff) or ""
        except (TypeError, ValueError):
            return ""
    try:
        return {Pk.ClientError.DECLINED_SIMULATION: "cancelled",
                Pk.ClientError.NOT_SUPPORTED: "not-supported"}.get(err.code, "")
    except AttributeError:
        return ""


def _exit_error(results, code):
    """GLib.Error equivalent to a transaction that ended without success."""
    err = results.get_error_code()
    if err is not None:
        return GLib.Error(err.get_details() or "", "pk-client-error-quark", 0xff + int(err.get_code()))
    if code in (Pk.ExitEnum.CANCELLED, Pk.ExitEnum.CANCELLED_PRIORITY):
        return GLib.Error("cancelled", "pk-client-error-quark",
                          0xff + int(Pk.ErrorEnum.TRANSACTION_CANCELLED))
    return GLib.Error(Pk.exit_enum_to_string(code) or "failed", "pk-client-error-quark",
                      0xff + int(Pk.ErrorEnum.INTERNAL_ERROR))


def classify(err):
    """(kind, message) for an exception from a PackageKit call."""
    if isinstance(err, GLib.Error) and err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
        return CANCELLED, tr("Cancelled.")
    name = _error_name(err)
    text = (getattr(err, "message", "") or str(err)).lower()
    if name in ("transaction-cancelled", "cancelled", "cancelled-priority"):
        return CANCELLED, tr("Cancelled.")
    # the apt backend does not wait for the lock of the package lists: it fails
    # with cannot-fetch-sources and "Could not get lock" (tested)
    if name in ("cannot-get-lock", "lock-required") or "could not get lock" in text \
            or "unable to lock" in text or "unable to acquire the dpkg frontend lock" in text:
        return LOCKED, tr("Another program is installing software. Wait until it finishes, "
                          "then try again.")
    if name == "no-network" or (name in ("cannot-fetch-sources", "repo-not-available",
                                         "package-download-failed", "internal-error", "")
                                and any(h in text for h in _NETWORK_HINTS)):
        return NO_NETWORK, tr("No internet connection. Connect to a network and try again.")
    if name in ("cannot-fetch-sources", "repo-not-available", "repo-not-found",
                "repo-configuration-error", "no-cache", "cannot-get-repo-list"):
        return REPO_UNREACHABLE, tr("The software sources cannot be reached right now. "
                                    "Try again later.")
    if name in ("package-download-failed", "package-corrupt", "transaction-error") and \
            ("download" in text or "fetch" in text or name == "package-download-failed"):
        return DOWNLOAD_FAILED, tr("The download was interrupted. Click “Update All” again: "
                                   "what was already downloaded is kept.")
    if name in ("no-space-on-device",):
        return NO_SPACE, tr("Not enough free disk space for the updates.")
    if name in ("not-authorized",) or "not authorized" in text or "authentication" in text:
        return NOT_AUTHORIZED, tr("The administrator password was not entered, so nothing "
                                  "was changed.")
    if name in ("dep-resolution-failed", "package-conflicts", "file-conflicts",
                "cannot-remove-system-package", "update-not-found", "cannot-install-repo-unsigned"):
        return CONFLICT, tr("These updates conflict with other installed software. Use "
                            "“Advanced: Synaptic Package Manager” to see the details.")
    if name in ("missing-gpg-signature", "bad-gpg-signature", "gpg-failure",
                "cannot-update-repo-unsigned", "package-not-trusted"):
        return SIGNATURE, tr("A package could not be verified, so it was not installed. "
                             "Try again later.")
    if name in ("package-failed-to-configure", "package-failed-to-install",
                "package-failed-to-remove", "failed-due-to-running-process") or \
            "returned an error code" in text:
        return INSTALL_FAILED, tr("An update could not be installed completely. Click “Repair Now” "
                                  "to finish the installation, then check for updates again.")
    if name in ("package-database-changed",):
        return FAILED, tr("The list of packages changed in the meantime. Check for updates again.")
    if "broken" in text or "dpkg was interrupted" in text or "unmet dependencies" in text:
        return BROKEN, tr("The package system needs a repair before updating. Use "
                          "“Advanced: Synaptic Package Manager” (Edit › Fix Broken Packages).")
    if isinstance(err, GLib.Error) and err.domain in ("g-dbus-error-quark", "g-io-error-quark"):
        return UNAVAILABLE, tr("The update service is not responding. Restart the computer "
                               "and try again.")
    return FAILED, tr("The update did not complete.")


def outcome_from_error(err):
    kind, message = classify(err)
    detail = getattr(err, "message", "") or str(err)
    return Outcome(kind, message, detail=detail.strip())


# ----------------------------------------------------------------- progress
def status_text(status, package_name=""):
    """What PackageKit is doing, as a short sentence for the progress line."""
    if Pk is None:
        return ""
    S = Pk.StatusEnum
    if status == S.WAITING_FOR_LOCK:
        return tr("Another program is installing software. Waiting for it to finish…")
    if status == S.WAITING_FOR_AUTH:
        return tr("Waiting for permission…")
    if status in (S.REFRESH_CACHE, S.DOWNLOAD_REPOSITORY, S.DOWNLOAD_PACKAGELIST,
                  S.DOWNLOAD_UPDATEINFO, S.DOWNLOAD_FILELIST, S.DOWNLOAD_CHANGELOG,
                  S.DOWNLOAD_GROUP):
        return tr("Checking the software sources…")
    if status == S.DOWNLOAD:
        return (tr("Downloading {name}…").format(name=package_name) if package_name
                else tr("Downloading updates…"))
    if status == S.DEP_RESOLVE:
        return tr("Checking dependencies…")
    if status in (S.SIG_CHECK, S.TEST_COMMIT):
        return tr("Verifying packages…")
    if status in (S.INSTALL, S.UPDATE, S.REMOVE, S.OBSOLETE, S.COMMIT, S.CLEANUP):
        return (tr("Installing {name}…").format(name=package_name) if package_name
                else tr("Installing updates…"))
    if status in (S.RUN_HOOK, S.SCAN_APPLICATIONS, S.GENERATE_PACKAGE_LIST, S.CHECK_LIBRARIES,
                  S.COPY_FILES, S.SCAN_PROCESS_LIST, S.CHECK_EXECUTABLE_FILES):
        return tr("Finishing the installation…")
    if status == S.CANCEL:
        return tr("Cancelling…")
    if status == S.FINISHED:
        return tr("Done.")
    return tr("Preparing…")


class Progress:
    """Snapshot of a transaction's progress, passed to the UI callback."""
    __slots__ = ("status", "text", "fraction", "can_cancel", "waiting_for_lock", "package",
                 "remaining")

    def __init__(self):
        self.remaining = None                # bytes still to download, None = unknown
        self.status = None
        self.text = ""
        self.fraction = None                 # 0..1, None = unknown
        self.can_cancel = False
        self.waiting_for_lock = False
        self.package = ""


# ----------------------------------------------------------------- the session
class Session:
    """One PackageKit client. Operations are asynchronous; at most one at a time."""

    def __init__(self):
        self.client = Pk.Client() if Pk else None
        self.cancellable = None
        self.busy = False
        self._progress = Progress()

    # --- helpers
    def _progress_cb(self, on_progress):
        def cb(progress, ptype, *_):
            p = self._progress
            try:
                if ptype == Pk.ProgressType.STATUS:
                    status = progress.props.status
                    if p.waiting_for_lock and status in (Pk.StatusEnum.WAIT, Pk.StatusEnum.SETUP,
                                                         Pk.StatusEnum.UNKNOWN):
                        return                   # still waiting: the daemon retries every few seconds
                    if status != p.status:
                        p.fraction = None        # the old percentage belongs to the old step
                    p.status = status
                    p.waiting_for_lock = status == Pk.StatusEnum.WAITING_FOR_LOCK
                elif ptype == Pk.ProgressType.PERCENTAGE:
                    pct = progress.props.percentage
                    p.fraction = pct / 100.0 if 0 <= pct <= 100 else None
                elif ptype == Pk.ProgressType.ALLOW_CANCEL:
                    p.can_cancel = bool(progress.props.allow_cancel)
                elif ptype == Pk.ProgressType.DOWNLOAD_SIZE_REMAINING:
                    left = progress.props.download_size_remaining
                    p.remaining = left if 0 <= left < 2 ** 63 else None
                elif ptype in (Pk.ProgressType.PACKAGE_ID, Pk.ProgressType.PACKAGE):
                    pid = progress.props.package_id or ""
                    p.package = pid.split(";")[0]
                else:
                    return
            except (AttributeError, TypeError):
                return
            p.text = status_text(p.status, p.package)
            if on_progress:
                on_progress(p)
        return cb

    def _start(self):
        self.cancellable = Gio.Cancellable()
        self.busy = True
        self._progress = Progress()

    def _finish(self, on_done, outcome):
        self.busy = False
        self.cancellable = None
        if on_done:
            on_done(outcome)

    def cancel(self):
        """Ask PackageKit to stop. It stops at once while downloading; while
        dpkg is installing it refuses (can_cancel is False) to avoid leaving a
        half-installed system."""
        if self.cancellable is not None:
            self.cancellable.cancel()

    def _call(self, method, args, on_progress, then, waited=0):
        """client.<method>_async(*args, cancellable, progress, ...) then then(results|error).

        When another program holds the APT lock (Synaptic, apt in a terminal,
        an unattended upgrade), the call is repeated every LOCK_RETRY seconds
        for up to LOCK_WAIT seconds, showing "Another program is installing
        software" meanwhile; Cancel stops the wait."""
        def ready(client, res, *_):
            results, err = None, None
            try:
                results = client.generic_finish(res)
                # a cancelled transaction finishes "successfully" with exit
                # code cancelled and no error (tested): make it an error
                code = results.get_exit_code()
                if code != Pk.ExitEnum.SUCCESS:
                    err = _exit_error(results, code)
            except GLib.Error as e:
                err = e
            if err is not None:
                if classify(err)[0] == LOCKED and waited < LOCK_WAIT:
                    self._wait_for_lock(method, args, on_progress, then, waited)
                    return
                then(None, err)
                return
            then(results, None)
        # keywords, without the user_data arguments: passing None for
        # progress_user_data made every progress call fail in PyGObject
        # ("expected tuple for callback user_data", tested)
        getattr(self.client, method + "_async")(*args, cancellable=self.cancellable,
                                                progress_callback=self._progress_cb(on_progress),
                                                callback_ready=ready)

    def _wait_for_lock(self, method, args, on_progress, then, waited):
        p = self._progress
        p.waiting_for_lock = True
        p.fraction = None
        p.can_cancel = True
        p.text = status_text(Pk.StatusEnum.WAITING_FOR_LOCK)
        if on_progress:
            on_progress(p)
        cancellable = self.cancellable

        def retry():
            if cancellable is None or cancellable.is_cancelled():
                then(None, GLib.Error("cancelled", "pk-client-error-quark",
                                      0xff + int(Pk.ErrorEnum.TRANSACTION_CANCELLED)))
            else:
                p.waiting_for_lock = False
                self._call(method, args, on_progress, then, waited + LOCK_RETRY)
            return False
        GLib.timeout_add_seconds(LOCK_RETRY, retry)

    # --- check
    def check(self, on_progress, on_done, refresh=True, force=False):
        """Refresh the package lists (when refresh) and list the updates with
        details. on_done(Outcome) with outcome.updates."""
        if self.client is None:
            on_done(Outcome(UNAVAILABLE, tr("The update service is not installed.")))
            return
        self._start()
        state = {"updates": [], "refresh_error": None, "refreshed": False}

        def after_refresh(_results, err):
            if err is not None:
                kind, _m = classify(err)
                if kind == CANCELLED:
                    self._finish(on_done, outcome_from_error(err))
                    return
                # without fresh lists the old ones still tell what was known
                state["refresh_error"] = err
            else:
                state["refreshed"] = refresh
            self._call("get_updates", (Pk.filter_bitfield_from_string("none"),),
                       on_progress, after_updates)

        def after_updates(results, err):
            if err is not None:
                self._finish(on_done, outcome_from_error(err))
                return
            ups = [Update(p.get_id(), Pk.info_enum_to_string(p.get_info()), p.get_summary())
                   for p in results.get_package_array()]
            # "blocked" = kept back by apt (held or not installable now)
            state["updates"] = ups
            if not ups:
                done()
                return
            self._call("get_details", ([u.id for u in ups],), on_progress, after_details)

        def after_details(results, err):
            if err is None:
                by_id = {u.id: u for u in state["updates"]}
                for d in results.get_details_array():
                    u = by_id.get(d.props.package_id)
                    if u is not None:
                        u.size = _bytes(d.props.size)
                        u.download_size = _bytes(d.props.download_size)
            self._call("get_update_detail", ([u.id for u in state["updates"]],),
                       on_progress, after_update_detail)

        def after_update_detail(results, err):
            olds = []
            if err is None:
                by_id = {u.id: u for u in state["updates"]}
                for d in results.get_update_detail_array():
                    u = by_id.get(d.props.package_id)
                    if u is None:
                        continue
                    replaced = list(d.props.updates or [])
                    if replaced:
                        u.old_id = replaced[0]
                        u.old_version = (replaced[0].split(";") + ["", ""])[1]
                        olds.append(replaced[0])
            if not olds:
                done()
                return
            self._call("get_details", (olds,), on_progress, after_old_details)

        def after_old_details(results, err):
            if err is None:
                by_old = {u.old_id: u for u in state["updates"] if u.old_id}
                for d in results.get_details_array():
                    u = by_old.get(d.props.package_id)
                    if u is not None:
                        u.old_size = _bytes(d.props.size)
            done()

        def done():
            ups = sorted(state["updates"], key=lambda u: (not u.security, u.name))
            err = state["refresh_error"]
            if err is not None:
                outcome = outcome_from_error(err)
                outcome.updates = ups            # what the previous lists say
            else:
                outcome = Outcome(OK, updates=ups)
                if state["refreshed"]:          # only a real check counts as "Last check"
                    record_check(len(ups), sum(1 for u in ups if u.security))
            outcome.held = held_packages()
            outcome.broken = broken_packages()
            self._finish(on_done, outcome)

        if refresh:
            self._call("refresh_cache", (force,), on_progress, after_refresh)
        else:
            after_refresh(None, None)

    # --- install
    def simulate(self, ids, on_progress, on_done):
        """What updating ids would do: outcome.additions/removals (names), or an error
        (dependency conflict) before anything is downloaded."""
        self._start()
        flags = Pk.transaction_flag_bitfield_from_string("simulate")

        def then(results, err):
            if err is not None:
                self._finish(on_done, outcome_from_error(err))
                return
            out = Outcome(OK)
            for p in results.get_package_array():
                info = Pk.info_enum_to_string(p.get_info())
                name = p.get_id().split(";")[0]
                if info in ("removing", "obsoleting", "downgrading"):
                    out.removals.append(name)
                elif info == "installing":
                    out.additions.append(p.get_id())
            if not out.additions:
                self._finish(on_done, out)
                return

            def sizes(results, err):
                # new dependencies take space too (download, installed size)
                if err is None:
                    out.extra = [(_bytes(d.props.download_size), _bytes(d.props.size))
                                 for d in results.get_details_array()]
                self._finish(on_done, out)
            self._call("get_details", (list(out.additions),), on_progress, sizes)
        self._call("update_packages", (flags, list(ids)), on_progress, then)

    def install(self, ids, on_progress, on_done, on_phase=None):
        """Download (cancellable), then install the updates. on_phase("download"|
        "install") marks the step; on_done(Outcome) with outcome.restart."""
        self._start()
        ids = list(ids)
        trusted = Pk.transaction_flag_bitfield_from_string("only-trusted")
        download_only = Pk.transaction_flag_bitfield_from_string("only-trusted;only-download")

        def after_download(_results, err):
            if err is not None:
                self._finish(on_done, outcome_from_error(err))
                return
            if on_phase:
                on_phase("install")
            self._call("update_packages", (trusted, ids), on_progress, after_install)

        def after_install(results, err):
            if err is not None:
                self._finish(on_done, outcome_from_error(err))
                return
            names = [i.split(";")[0] for i in ids]
            restart = ""
            try:
                worst = results.get_require_restart_worst()
                if worst in (Pk.RestartEnum.SYSTEM, Pk.RestartEnum.SECURITY_SYSTEM):
                    restart = "system"
                elif worst in (Pk.RestartEnum.SESSION, Pk.RestartEnum.SECURITY_SESSION):
                    restart = "session"
            except (AttributeError, TypeError):
                pass
            if restart != "system" and (os.path.exists(REBOOT_FLAG)
                                        or any(RESTART_PACKAGES.match(n) for n in names)):
                restart = "system"
            record_success(len(ids), restart)
            self._finish(on_done, Outcome(OK, restart=restart))

        if on_phase:
            on_phase("download")
        self._call("update_packages", (download_only, ids), on_progress, after_download)


    # --- repair
    def repair(self, on_progress, on_done):
        """Finish an installation left half done (dpkg --configure -a, missing
        dependencies), the graphical "Fix Broken Packages". Needs the password."""
        self._start()
        flags = Pk.transaction_flag_bitfield_from_string("only-trusted")

        def then(_results, err):
            if err is not None:
                self._finish(on_done, outcome_from_error(err))
                return
            out = Outcome(OK)
            out.broken = broken_packages()
            if out.broken:
                out.kind = BROKEN
                out.message = tr("The repair did not finish. Use “Advanced: Synaptic Package "
                                 "Manager” (Edit › Fix Broken Packages).")
            self._finish(on_done, out)
        self._call("repair_system", (flags,), on_progress, then)


def run_sync(start, timeout=900):
    """Run an asynchronous Session operation to the end (command line, tests).
    start(on_done) begins it; returns the Outcome."""
    loop = GLib.MainLoop()
    box = {}

    def done(outcome):
        box["outcome"] = outcome
        loop.quit()

    def expired():
        box.setdefault("outcome", Outcome(FAILED, tr("The update service did not answer in time.")))
        loop.quit()
        return False
    GLib.timeout_add_seconds(timeout, expired)
    start(done)
    if "outcome" not in box:
        loop.run()
    return box["outcome"]


# ----------------------------------------------------------------- disk space
def space_needed(updates, extra_ids_sizes=()):
    """(download_bytes, install_growth_bytes) for a list of Update."""
    download = sum(u.download_size for u in updates)
    growth = sum(max(0, u.size - (u.old_size or 0)) if u.old_size else u.size for u in updates)
    for dl, size in extra_ids_sizes:
        download += dl
        growth += size
    return download, growth


def free_bytes(path):
    while path and not os.path.exists(path):
        path = os.path.dirname(path)
    try:
        return shutil.disk_usage(path or "/").free
    except OSError:
        return None


def check_space(updates, extra=()):
    """None when there is room, otherwise a message saying how much is missing.
    The download goes to /var/cache/apt/archives, the files to /usr: on the
    same file system both must fit together."""
    download, growth = space_needed(updates, extra)
    need = []
    try:
        same = os.stat(APT_ARCHIVES).st_dev == os.stat("/usr").st_dev
    except OSError:
        same = True
    if same:
        need.append(("/usr", download + growth + SPACE_MARGIN))
    else:
        need.append((APT_ARCHIVES, download + SPACE_MARGIN // 2))
        need.append(("/usr", growth + SPACE_MARGIN // 2))
    for path, n in need:
        free = free_bytes(path)
        if free is not None and free < n:
            return tr("Not enough free disk space: the updates need {need}, only {free} is "
                      "free. Delete some files or empty the Trash, then try again.").format(
                need=human_size(n), free=human_size(free))
    return None


# ----------------------------------------------------------------- held packages
def held_packages():
    """Packages on hold (apt-mark hold): PackageKit does not list their
    updates. ZETA RAYS holds Hyprland (its patched build)."""
    held = []
    try:
        with open("/var/lib/dpkg/status", encoding="utf-8", errors="replace") as f:
            name = None
            for line in f:
                if line.startswith("Package: "):
                    name = line[9:].strip()
                elif line.startswith("Status: hold ") and name:
                    held.append(name)
    except OSError:
        pass
    return sorted(held)


_FINAL_STATES = ("installed", "not-installed", "config-files")


def broken_packages():
    """Packages dpkg left half done (unpacked, half-configured, waiting for
    triggers...) or marked reinst-required: PackageKit then lists no updates,
    and the page would wrongly say "up to date"."""
    broken = []
    try:
        with open("/var/lib/dpkg/status", encoding="utf-8", errors="replace") as f:
            name = None
            for line in f:
                if line.startswith("Package: "):
                    name = line[9:].strip()
                elif line.startswith("Status: ") and name:
                    parts = line.split()
                    if len(parts) == 4 and (parts[3] not in _FINAL_STATES or parts[2] != "ok"):
                        broken.append(name)
    except OSError:
        pass
    return sorted(set(broken))


# ----------------------------------------------------------------- history
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(data):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def _update_state(**values):
    data = load_state()
    data.update(values)
    save_state(data)


def record_check(count, security):
    _update_state(last_check=int(time.time()), available=count, security=security)


def record_success(count, restart):
    _update_state(last_success=int(time.time()), installed=count, available=0, security=0,
                  restart=restart, restart_boot=boot_id())


def boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip()
    except OSError:
        return ""


APT_UPDATE_STAMP = "/var/lib/apt/periodic/update-success-stamp"


def last_index_refresh():
    """Time of the last package list download by any program (apt, Synaptic,
    PackageKit, the daily timer).

    Not the time of the Release files: apt gives them the date the archive
    published them (the server's Last-Modified), so a list downloaded now
    could show a time hours ago. The folder of the lists changes when a
    download replaces a file in it, and the daily timer leaves a stamp after
    a successful update: both are local times of this computer."""
    times = []
    for path in (APT_LISTS, APT_UPDATE_STAMP):
        try:
            times.append(os.path.getmtime(path))
        except OSError:
            pass
    if not glob.glob(os.path.join(APT_LISTS, "*Release")):
        return None                     # no package lists at all
    return int(max(times)) if times else None


def apt_upgrades():
    """Completed apt runs that upgraded packages, by any program, newest last:
    [(end time, command line, [package names])]. From /var/log/apt/history.log
    (and its last rotation), which every user can read."""
    runs = []
    for path in (APT_HISTORY + ".1.gz", APT_HISTORY):
        try:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for block in text.split("\n\n"):
            up = re.search(r"^Upgrade: (.*)$", block, re.M)
            if not up or re.search(r"^Error: ", block, re.M):
                continue
            cmd = re.search(r"^Commandline: (.*)$", block, re.M)
            if cmd and ("--dry-run" in cmd.group(1) or "--simulate" in cmd.group(1)):
                continue                       # logged, but nothing really changed
            m = re.search(r"^End-Date: (\d{4}-\d\d-\d\d)\s+(\d\d:\d\d:\d\d)", block, re.M)
            if not m:
                continue
            try:
                t = int(time.mktime(time.strptime(m.group(1) + " " + m.group(2), "%Y-%m-%d %H:%M:%S")))
            except (ValueError, OverflowError):
                continue
            # "libfoo:arm64 (1.0, 1.1), libbar:arm64 (2.0, 2.1)"
            names = re.findall(r"(?:^|\), )([^\s:(]+)(?::[\w-]+)? \(", up.group(1))
            runs.append((t, cmd.group(1) if cmd else "", names))
    runs.sort(key=lambda r: r[0])
    return runs


def _is_update_run(cmdline):
    # an "apt install" that upgrades a library along the way is not an update
    return bool(re.search(r"upgrade|update-packages", cmdline))


def _is_automatic_run(cmdline):
    return "unattended-upgrade" in cmdline


def last_apt_upgrade(runs=None):
    """Time of the last completed update run (apt upgrade, Synaptic's upgrade,
    PackageKit, unattended-upgrades). None if unknown."""
    times = [t for t, cmd, _n in (apt_upgrades() if runs is None else runs) if _is_update_run(cmd)]
    return times[-1] if times else None


def last_automatic_update(runs=None):
    times = [t for t, cmd, _n in (apt_upgrades() if runs is None else runs) if _is_automatic_run(cmd)]
    return times[-1] if times else None


def boot_time():
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime "):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def restart_pending(runs=None):
    """A restart is needed: the system says so, our last install said so, or an
    update since this boot replaced the kernel, the C library, systemd,
    Hyprland... (automatic updates included)."""
    if os.path.exists(REBOOT_FLAG):
        return True
    data = load_state()
    if data.get("restart") == "system" and boot_id() and data.get("restart_boot") == boot_id():
        return True
    booted = boot_time()
    if booted is None:
        return False
    for t, _cmd, names in (apt_upgrades() if runs is None else runs):
        if t > booted and any(RESTART_PACKAGES.match(n) for n in names):
            return True
    return False


# ----------------------------------------------------------------- automatic security updates
AUTO_HELPER = "/usr/libexec/zeta-auto-updates"


def auto_updates_supported():
    return os.access(AUTO_HELPER, os.X_OK) and os.path.exists("/usr/bin/unattended-upgrade")


def auto_updates_enabled():
    """The value apt really uses (all apt.conf.d files together)."""
    try:
        r = subprocess.run(["apt-config", "shell", "V", "APT::Periodic::Unattended-Upgrade"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    m = re.search(r"V='(\d+)'", r.stdout)
    return bool(m and m.group(1) != "0")


def set_auto_updates(on):
    """(ok, message). Through pkexec: the administrator's password is asked."""
    try:
        r = subprocess.run(["pkexec", AUTO_HELPER, "on" if on else "off"],
                           capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return False, tr("Could not change automatic updates.")
    if r.returncode == 0:
        return True, ""
    if r.returncode in (126, 127):           # password dialog dismissed, or not allowed
        return False, tr("The administrator password was not entered, so nothing was changed.")
    if r.returncode == 3:
        return False, tr("Not available in the live session: install ZETA RAYS first.")
    return False, tr("Could not change automatic updates.")


def summary():
    """Everything the page shows before any check: dates, counts, restart."""
    data = load_state()
    runs = apt_upgrades()
    last_check = max([t for t in (data.get("last_check"), last_index_refresh()) if t] or [0]) or None
    last_success = max([t for t in (data.get("last_success"), last_apt_upgrade(runs)) if t] or [0]) or None
    return {"last_check": last_check, "last_success": last_success,
            "last_automatic": last_automatic_update(runs),
            "available": data.get("available"), "security": data.get("security", 0),
            "restart": restart_pending(runs), "reminder": bool(data.get("reminder", False)),
            "broken": broken_packages(),
            "auto": auto_updates_enabled() if auto_updates_supported() else None}


def next_action(info):
    """Stable key of the recommended next step."""
    if info.get("broken"):
        return "repair"
    if info.get("restart"):
        return "restart"
    if not info.get("last_check") or time.time() - info["last_check"] > CHECK_EVERY:
        return "check"
    if info.get("security"):
        return "install-security"
    if info.get("available"):
        return "install"
    return "up-to-date-auto" if info.get("auto") else "up-to-date"


def next_action_text(key):
    return {
        "repair": tr("Click “Repair Now” to finish the installation that was left incomplete."),
        "restart": tr("Restart the computer to finish installing the updates."),
        "check": tr("Check for updates."),
        "install-security": tr("Install the security updates as soon as possible."),
        "install": tr("Install the available updates."),
        "up-to-date-auto": tr("Nothing to do. Security updates are installed automatically; "
                              "check now and then for the other updates."),
        "up-to-date": tr("Nothing to do. Check again in a few days, or turn on the weekly "
                         "reminder."),
    }.get(key, "")


def format_date(t):
    if not t:
        return tr("Never")
    lt = time.localtime(t)
    today = time.localtime()
    clock = time.strftime("%H:%M", lt)
    if lt.tm_year == today.tm_year and lt.tm_yday == today.tm_yday:
        return tr("Today, {time}").format(time=clock)
    yesterday = time.localtime(time.time() - 86400)
    if lt.tm_year == yesterday.tm_year and lt.tm_yday == yesterday.tm_yday:
        return tr("Yesterday, {time}").format(time=clock)
    return time.strftime("%x", lt) + ", " + clock


# ----------------------------------------------------------------- reminder
REMINDER_TIMER = "zeta-update-reminder.timer"


def set_reminder(on):
    """Weekly reminder (off by default). It only notifies; it never installs."""
    _update_state(reminder=bool(on))
    cmd = ["systemctl", "--user", "enable" if on else "disable", "--now", REMINDER_TIMER]
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, timeout=15)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def reminder_enabled():
    return bool(load_state().get("reminder", False))
