# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — printers (CUPS).

The standard CUPS tools are used (lpstat, lpinfo, lpadmin, lp). The user is
in the lpadmin group, so they can add and remove printers without a
password, as on any desktop system.

The computer does not distinguish a Wi-Fi printer from a wired one: both are
"on the network" and are found the same way (DNS-SD/mDNS, i.e. printer
Bonjour, and SNMP for older network printers). Driverless printing is always
tried first (IPP Everywhere, supported by every printer since 2013, USB ones
too thanks to ipp-usb); only if the printer does not support it do we look
for a suitable driver.
"""
import os
import re
import socket
import subprocess

from i18n import tr

LPADMIN = "/usr/sbin/lpadmin"
LPINFO = "/usr/sbin/lpinfo"
TEST_PAGE = "/usr/share/cups/data/default-testpage.pdf"
_ENV = dict(os.environ, LANG="C", LC_ALL="C", LANGUAGE="C")


def _cmd(argv, timeout=20):
    """(code, stdout, stderr), never raising."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=_ENV, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", tr("the printer did not respond in time")
    except OSError as e:
        return 127, "", e.strerror or str(e)


def manageable():
    """True if this user can add printers (lpadmin group)."""
    try:
        import grp
        gid = grp.getgrnam("lpadmin").gr_gid
    except (KeyError, ImportError):
        return False
    return os.geteuid() == 0 or gid in os.getgroups()


def service_active():
    rc, out, _ = _cmd(["lpstat", "-r"], 5)
    return rc == 0 and "not running" not in out


# ------------------------------------------------------------- list
def listing():
    """Configured printers: [{name, description, uri, state, default,
    jobs, connection}]."""
    _rc, out_v, _ = _cmd(["lpstat", "-v"], 8)
    uri = {}
    for r in out_v.splitlines():
        m = re.match(r"device for (\S+): (.+)$", r.strip())
        if m:
            uri[m.group(1)] = m.group(2).strip()
    if not uri:
        return []
    _rc, out_d, _ = _cmd(["lpstat", "-d"], 5)
    m = re.search(r"system default destination: (\S+)", out_d)
    default = m.group(1) if m else None
    _rc, out_p, _ = _cmd(["lpstat", "-l", "-p"], 8)
    state, descr = {}, {}
    current = None
    for r in out_p.splitlines():
        m = re.match(r"printer (\S+) (.*)", r)
        if m:
            current = m.group(1)
            t = m.group(2)
            if "disabled" in t:
                state[current] = "stopped"
            elif "now printing" in t:
                state[current] = "printing"
            else:
                state[current] = "ready"
            continue
        m = re.match(r"\s+Description: (.*)", r)
        if m and current:
            descr[current] = m.group(1).strip()
    _rc, out_o, _ = _cmd(["lpstat", "-o"], 8)
    jobs = {}
    for r in out_o.splitlines():
        m = re.match(r"(\S+)-\d+\s", r)
        if m:
            jobs[m.group(1)] = jobs.get(m.group(1), 0) + 1
    res = []
    for name, u in uri.items():
        res.append({
            "name": name,
            "description": (descr.get(name) or name).replace("_", " ").strip(),
            "uri": u,
            "state": state.get(name, "ready"),
            "default": name == default,
            "jobs": jobs.get(name, 0),
            "connection": connection(u),
        })
    res.sort(key=lambda s: (not s["default"], s["description"].lower()))
    return res


def connection(uri):
    u = uri.lower()
    # ipp-usb publishes USB printers as network printers of the computer
    # itself, on ports 60000 and up
    if u.startswith("usb:") or "localhost" in u or "127.0.0.1" in u or \
            "ipp-usb" in u or re.search(r":6\d{4}/", u):
        return "USB"
    if u.startswith(("cups-pdf:", "file:")):
        return tr("On this computer")
    return tr("Network (Wi-Fi or cable)")


# ------------------------------------------------------------- discovery
def search(seconds=8):
    """Connected or network printers not yet added.

    [{uri, name, model, device_id, connection}]. A network printer
    announces itself several times (IPP, IPPS, port 9100...): only one is
    kept, preferring the announcement that allows driverless printing."""
    rc, out, _ = _cmd([LPINFO, "-l", "-v", "--timeout", str(seconds),
                       "--include-schemes", "dnssd,usb,snmp"], seconds + 15)
    found, entry = [], None
    for r in out.splitlines():
        m = re.match(r"Device: uri = (.+)$", r.strip())
        if m:
            entry = {"uri": m.group(1).strip()}
            found.append(entry)
            continue
        m = re.match(r"\s*(class|info|make-and-model|device-id|location) = (.*)$", r)
        if m and entry is not None:
            entry[m.group(1)] = m.group(2).strip()
    # cups-browsed creates a queue by itself for every IPP printer on the
    # network (implicitclass:// address): that one is already set up and
    # must not be offered again
    configured = listing()
    existing = {s["uri"] for s in configured}
    seen_names = {_key(s["description"]) for s in configured} | \
        {_key(s["name"]) for s in configured}
    choices = {}
    for v in found:
        u = v["uri"]
        # usb:// without a printer (just the scheme), backend with no results
        if u in ("usb", "dnssd", "snmp") or "://" not in u:
            continue
        name = (v.get("info") or v.get("make-and-model") or u).strip()
        if not name or name.lower() in ("unknown", "unknown unknown"):
            name = u
        name = _clean_name(name)
        model = v.get("make-and-model", "")
        if model.lower() in ("unknown", ""):
            model = ""
        model = _clean_name(model) if model else ""
        key = re.sub(r"[^a-z0-9]", "", (model or name).lower())[:40] or u
        score = 3 if u.startswith("dnssd:") else (2 if u.startswith("usb:") else 1)
        if u in existing or _key(name) in seen_names or (model and _key(model) in seen_names):
            continue
        previous = choices.get(key)
        if previous is None or score > previous["_score"]:
            choices[key] = {"uri": u, "name": name, "model": model,
                            "device_id": v.get("device-id", ""),
                            "connection": connection(u),
                            "_score": score}
    res = []
    for s in choices.values():
        s.pop("_score", None)
        res.append(s)
    res.sort(key=lambda s: s["name"].lower())
    return res


def _key(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def ensure_default():
    """If there are printers but none is the default, the first one becomes
    the default: programs print right away without asking where."""
    if not manageable():
        return
    items = listing()
    if items and not any(s["default"] for s in items):
        _cmd([LPADMIN, "-d", items[0]["name"]], 10)


def _clean_name(name):
    """«Canon Canon PIXMA (driverless)» -> «Canon PIXMA»."""
    name = re.sub(r"\s*\((driverless|IPP Everywhere|IPP-USB)\)\s*$", "", name, flags=re.I)
    words = name.split()
    if len(words) > 1 and words[0].lower() == words[1].lower():
        words = words[1:]
    return " ".join(words) or name


# ------------------------------------------------------------- adding
def _queue_name(text):
    """A valid CUPS name (letters, digits, _), unique among the printers."""
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:60] or "Printer"
    existing = {s["name"] for s in listing()}
    name, n = base, 2
    while name in existing:
        name, n = "%s_%d" % (base, n), n + 1
    return name


def _brand(device_id, model):
    m = re.search(r"(?:MFG|MANUFACTURER):([^;]+)", device_id or "")
    brand = (m.group(1) if m else (model or "").split(" ")[0]).strip().lower()
    return {"hewlett-packard": "hp"}.get(brand, brand)


def _driver_for(device_id, model):
    """The driver CUPS considers best for this printer, or None.
    Only a driver of the same brand is accepted: if lpinfo does not find the
    model, it still suggests the first driver in its list."""
    brand = _brand(device_id, model)
    if not brand:
        return None
    for opts, val in (("--device-id", device_id), ("--make-and-model", model)):
        if not val:
            continue
        _rc, out, _ = _cmd([LPINFO, "-m", opts, val], 30)
        for r in out.splitlines():
            ppd, _sp, descr = r.partition(" ")
            if not ppd or ppd in ("everywhere", "raw") or "pwgrast" in ppd:
                continue
            d = descr.lower().replace("hewlett-packard", "hp")
            if d.startswith(brand) or (" " + brand + " ") in (" " + d):
                return ppd, descr or ppd
    return None


def _first_printer():
    _rc, out, _ = _cmd(["lpstat", "-d"], 5)
    return "system default destination:" not in out


def add(uri, display_name, device_id="", model=""):
    """Add the printer. Returns (ok, message)."""
    if not manageable():
        return False, tr("This user cannot add printers: membership in the lpadmin group is required.")
    queue = _queue_name(display_name)
    descr = display_name[:120]
    was_first = _first_printer()
    rc, _o, err = _cmd([LPADMIN, "-p", queue, "-E", "-v", uri, "-m", "everywhere",
                        "-D", descr], 60)
    mode = tr("driverless")
    if rc != 0:
        _cmd([LPADMIN, "-x", queue], 10)     # lpadmin leaves the queue half-created
        driver = _driver_for(device_id, model)
        if driver is None:
            return False, tr("The printer does not support driverless printing and no suitable driver "
                             "is installed ({error}).").format(error=err or tr("no details"))
        rc, _o, err = _cmd([LPADMIN, "-p", queue, "-E", "-v", uri, "-m", driver[0],
                            "-D", descr], 60)
        mode = tr("driver {name}").format(name=driver[1])
        if rc != 0:
            _cmd([LPADMIN, "-x", queue], 10)
            return False, tr("Could not add the printer: {error}").format(error=err or rc)
    if was_first:
        _cmd([LPADMIN, "-d", queue], 10)
    _cmd([LPADMIN, "-p", queue, "-o", "printer-error-policy=retry-job"], 10)
    return True, tr("“{name}” added ({method}).").format(name=descr, method=mode)


_VALID_HOST = re.compile(r"^[A-Za-z0-9.\-]+(:\d{2,5})?$|^\[?[0-9A-Fa-f:]+\]?$")


def add_address(host):
    """Add a network printer from its IP address or name.

    Needed when automatic discovery does not see it (an office network with
    mDNS announcements blocked, a printer on another subnet)."""
    host = (host or "").strip()
    host = re.sub(r"^[a-z]+://", "", host).split("/")[0]
    if not host or not _VALID_HOST.match(host):
        return False, tr("Enter the printer's address, for example 192.168.1.50.")
    port = None
    m = re.match(r"^([A-Za-z0-9.\-]+):(\d{2,5})$", host)   # 192.168.1.50:8631
    if m:
        host, port = m.group(1), int(m.group(2))
    elif ":" in host and not host.startswith("["):
        host = "[%s]" % host        # IPv6 in URIs goes in brackets
    bare_host = host.strip("[]")
    if port:
        if not _port_open(bare_host, port):
            return False, tr("No printer responds at {address}:{port}.").format(address=bare_host, port=port)
        for uri in ("ipp://%s:%d/ipp/print" % (host, port), "ipp://%s:%d/" % (host, port)):
            ok, msg = _test_everywhere(uri, bare_host)
            if ok:
                return ok, msg
        return False, tr("Something is listening on port {port}, but it is not an IPP printer.").format(port=port)
    ports = {p: _port_open(bare_host, p) for p in (631, 443, 9100)}
    if not any(ports.values()):
        return False, tr("No printer responds at {address}. Check that it is turned on and on the "
                         "same network (Wi-Fi or cable).").format(address=bare_host)
    if ports[631] or ports[443]:
        for uri in ("ipp://%s/ipp/print" % host, "ipps://%s/ipp/print" % host,
                    "ipp://%s/ipp" % host, "ipp://%s/" % host):
            ok, msg = _test_everywhere(uri, bare_host)
            if ok:
                return ok, msg
    was_first = _first_printer()
    if ports[9100]:
        # Network printer without IPP: port 9100 and the generic PCL driver,
        # which almost every laser printer understands.
        queue = _queue_name("Printer_" + bare_host)
        rc, _o, err = _cmd([LPADMIN, "-p", queue, "-E", "-v", "socket://%s:9100" % host,
                            "-m", "drv:///sample.drv/generpcl.ppd",
                            "-D", tr("Printer {address}").format(address=bare_host)], 30)
        if rc != 0:
            rc, _o, err = _cmd([LPADMIN, "-p", queue, "-E", "-v", "socket://%s:9100" % host,
                                "-m", "gutenprint.5.3://pcl-g_5e/expert",
                                "-D", tr("Printer {address}").format(address=bare_host)], 30)
        if rc == 0:
            if was_first:
                _cmd([LPADMIN, "-d", queue], 10)
            return True, tr("Printer {address} added with the generic PCL driver.").format(address=bare_host)
        _cmd([LPADMIN, "-x", queue], 10)
        return False, tr("Could not add the printer: {error}").format(error=err)
    return False, tr("Printer {address} responds but does not accept network printing.").format(address=bare_host)


def _test_everywhere(uri, bare_host):
    was_first = _first_printer()
    queue = _queue_name("Printer_" + bare_host)
    rc, _o, _err = _cmd([LPADMIN, "-p", queue, "-E", "-v", uri, "-m", "everywhere"], 45)
    if rc != 0:
        _cmd([LPADMIN, "-x", queue], 10)
        return False, ""
    # the printer's real name, read from the printer itself
    _rc, out, _ = _cmd(["lpoptions", "-p", queue], 8)
    m = re.search(r"printer-make-and-model='([^']+)'", out) or \
        re.search(r"printer-make-and-model=(\S+)", out)
    descr = re.sub(r"\s*-\s*IPP Everywhere.*$", "", m.group(1)) if m else ""
    if descr.lower() in ("", "printer", "unknown"):
        descr = tr("Printer {address}").format(address=bare_host)
    _cmd([LPADMIN, "-p", queue, "-D", descr, "-o", "printer-error-policy=retry-job"], 10)
    if was_first:
        _cmd([LPADMIN, "-d", queue], 10)
    return True, tr("“{name}” added (driverless).").format(name=descr)


def _port_open(host, port, wait=2.5):
    try:
        with socket.create_connection((host, port), timeout=wait):
            return True
    except OSError:
        return False


# ------------------------------------------------------------- actions
def remove(name):
    rc, _o, err = _cmd([LPADMIN, "-x", name], 15)
    return rc == 0, err


def set_default(name):
    rc, _o, err = _cmd([LPADMIN, "-d", name], 10)
    return rc == 0, err


def test_page(name):
    test = TEST_PAGE if os.path.exists(TEST_PAGE) else "/usr/share/cups/data/testprint"
    rc, _o, err = _cmd(["lp", "-d", name, "-t", tr("ZETA RAYS test page"), test], 20)
    return rc == 0, err


def resume(name):
    """Bring back a printer that was stopped by an error."""
    rc1, _o, e1 = _cmd(["cupsenable", name], 10)
    rc2, _o, e2 = _cmd(["cupsaccept", name], 10)
    return rc1 == 0 and rc2 == 0, e1 or e2


def cancel_jobs(name):
    rc, _o, err = _cmd(["cancel", "-a", name], 10)
    return rc == 0, err
