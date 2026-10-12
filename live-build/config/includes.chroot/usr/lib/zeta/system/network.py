# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — networking (NetworkManager via nmcli): status, Wi-Fi, VPN, proxy."""
import os
import re

from i18n import tr

from . import run

VPN_TYPES = ("vpn", "wireguard")

# nmcli translates states and messages into the system language (e.g.
# Italian "connesso", "abilitato"): whenever its output is parsed, English is
# always used. C.UTF-8
# rather than C, so network names with accented letters stay intact.
NMCLI = ["env", "LC_ALL=C.UTF-8", "LANGUAGE=C", "nmcli"]


def _split(line):
    """Split a `nmcli -t` line, honoring ':' characters escaped with '\\'."""
    parts, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _rows(args, timeout=8):
    out = run(NMCLI + ["-t"] + args, timeout=timeout)
    return [_split(l) for l in (out or "").splitlines() if l.strip()]


def nice_name(conn, typ):
    """Display name: NetworkManager's automatic names become readable."""
    # the automatic name in English or as NetworkManager writes it in Italian  # i18n-data
    m = re.match(r"^(Wired connection|Connessione via cavo)\s*(\d+)$", conn or "")  # i18n-data
    if m:
        if m.group(2) == "1":
            return tr("Wired connection")
        return tr("Wired connection {n}").format(n=m.group(2))
    return conn


def status():
    """Main connection: {kind, name, label, device, ip, connected}."""
    info = {"kind": "none", "name": "", "label": "", "device": "", "ip": "", "connected": False}
    for dev, typ, state, conn in _rows(["-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]):
        if state == "connected" and typ in ("ethernet", "wifi"):
            info.update(kind=typ, name=conn, device=dev, connected=True,
                        label=nice_name(conn, typ))
            break
    if info["device"]:
        for row in _rows(["-f", "IP4.ADDRESS", "device", "show", info["device"]]):
            if len(row) > 1 and row[1]:
                info["ip"] = row[1].split("/")[0]
                break
    return info


def connectivity():
    """Internet status according to NetworkManager: full, limited, portal, none, unknown.

    Without --check: reads NetworkManager's last check, does not wait for the network.
    """
    state = (run(NMCLI + ["-t", "networking", "connectivity"]) or "").strip()
    return state if state in ("full", "limited", "portal", "none") else "unknown"


def wifi_enabled():
    return (run(NMCLI + ["-t", "radio", "wifi"]) or "").strip() == "enabled"


def has_wifi():
    return any(typ == "wifi" for _d, typ, *_ in _rows(["-f", "DEVICE,TYPE", "device"]))


def set_wifi(on):
    run(NMCLI + ["radio", "wifi", "on" if on else "off"])


def wifi_networks(rescan=False):
    """Visible Wi-Fi networks, the strongest per name: [{ssid, signal, secure, active}]."""
    args = ["-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
            "--rescan", "yes" if rescan else "auto"]
    best = {}
    for row in _rows(args, timeout=15):
        if len(row) < 4 or not row[1]:
            continue
        inuse, ssid, signal, sec = row[0], row[1], row[2], row[3]
        try:
            signal = int(signal)
        except ValueError:
            signal = 0
        net = {"ssid": ssid, "signal": signal, "secure": bool(sec and sec != "--"),
               "active": inuse.strip() == "*"}
        if ssid not in best or net["active"] or signal > best[ssid]["signal"]:
            best[ssid] = net
    return sorted(best.values(), key=lambda n: (not n["active"], -n["signal"]))


def known_connection(ssid):
    for name, typ in _rows(["-f", "NAME,TYPE", "connection", "show"]):
        if typ == "802-11-wireless" and name == ssid:
            return True
    return False


def _nmcli(args, input_=None, timeout=45):
    """nmcli in English (so messages can be recognized, see _reason) and with
    a wait limit: without --wait a network that did not respond kept the
    interface on "Connecting…" for a minute and a half."""
    import os
    import subprocess
    wait = ["--wait", str(max(5, timeout - 10))]
    try:
        r = subprocess.run(["nmcli"] + wait + args, input=input_, capture_output=True, text=True,
                           timeout=timeout, env=dict(os.environ, LC_ALL="C.UTF-8", LANGUAGE="C"))
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "timeout"
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def known_wifi():
    """The names of the saved Wi-Fi networks (a single call)."""
    return {name for name, typ in _rows(["-f", "NAME,TYPE", "connection", "show"])
            if typ == "802-11-wireless"}


def _reason(text):
    t = text.lower()
    if ("secrets were required" in t or "psk: property is invalid" in t or "no secrets" in t
            or "802-1x" in t or "wrong password" in t or "(7)" in t):
        return "password"
    if "no network with ssid" in t or "not found" in t and "ssid" in t:
        return "not_found"
    if "timeout" in t or "timed out" in t:
        return "timeout"
    return "other"


def _wifi_dev():
    for dev, typ in _rows(["-f", "DEVICE,TYPE", "device"]):
        if typ == "wifi":
            return dev
    return None


# What nmcli --ask prints (tested with NetworkManager 1.52 and simulated
# access points, October 1):
#  - the line "Password (802-11-wireless-security.psk):" appears twice EVEN
#    when everything works: nmcli prints it again after "successfully
#    activated" and when the timeout expires. Counting it made a successful
#    connection report "wrong password", and the profile just connected was
#    deleted: with the right password you could never connect.
#  - the real rejection is NetworkManager ASKING AGAIN for the password: the
#    header below shows up again (every ~4 s until it gives up).
_PASSWORD_PROMPT = "passwords or encryption keys are required"
_SUCCESS = "successfully activated"


def _read_output(text):
    """Return "success", "rejected" (NetworkManager asked for the password
    again) or None."""
    t = (text or "").lower()
    if _SUCCESS in t:
        return "success"
    if t.count(_PASSWORD_PROMPT) >= 2:
        return "rejected"
    return None


def _activate_connection(args, password, limit=40):
    """Run nmcli, reading what it prints while it works. With --ask nmcli
    asks for the password once (and gets it from stdin: it does not show up
    in the process list). If NetworkManager asks for it a second time it has
    rejected it: stop right away instead of waiting for the timeout (before,
    the error arrived after 40 s, or turned into "not responding")."""
    import os
    import subprocess
    import threading
    import time
    cmd = ["nmcli", "--wait", str(limit)] + args
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, env=dict(os.environ, LC_ALL="C.UTF-8", LANGUAGE="C"))
    except OSError as e:
        return 1, str(e), None
    try:
        p.stdin.write((password or "") + "\n")
        p.stdin.close()
    except OSError:
        pass
    lines = []

    def read():
        # nmcli prints the prompt without a newline: read it piece by piece
        while True:
            chunk = p.stdout.read(1) if p.stdout else ""
            if not chunk:
                break
            lines.append(chunk)
    t = threading.Thread(target=read, daemon=True)
    t.start()
    deadline = time.monotonic() + limit + 5
    rejected = False
    while p.poll() is None and time.monotonic() < deadline:
        time.sleep(0.2)
        state = _read_output("".join(lines))
        if state == "success":
            break                                    # nmcli is finishing on its own
        if state == "rejected":
            rejected = True
            break
    try:
        p.wait(timeout=3)                            # if it finished by itself, its result counts
    except subprocess.SubprocessError:
        pass
    killed = p.poll() is None
    if killed:
        p.kill()
        try:
            p.wait(timeout=5)
        except subprocess.SubprocessError:
            pass
    t.join(timeout=2)
    out = "".join(lines).strip()
    if _read_output(out) == "success":
        return 0, out, None
    if rejected or _read_output(out) == "rejected":
        return 1, out, "password"
    if killed:
        return 1, out, "timeout"
    return p.returncode, out, None


def _wait_for_network(ssid, within=15):
    """Is the network visible? Right after turning Wi-Fi on (or reloading the
    adapter) the list is empty for a few seconds, and NetworkManager only
    accepts a new scan every so often: keep looking for up to 15 s instead of
    answering "can't see it" on the third try (tested: 6 s was not enough
    after reloading the adapter)."""
    import time
    deadline = time.monotonic() + within
    first = True
    while True:
        _rc, out = _nmcli(["-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "auto" if first else "yes"],
                          timeout=20)
        if ssid in {line.replace("\\:", ":") for line in out.splitlines()}:
            return True
        first = False
        if time.monotonic() >= deadline:
            return False
        time.sleep(2)


def _key_rejected(since):
    """True if wpa_supplicant logged that the key is wrong (WRONG_KEY) since
    the given time; False if it did not; None if the journal cannot be read
    (user not in the adm group, e.g. on the live system).

    Needed because NetworkManager, on the first connection, asks for the
    password again after ANY failed attempt: a wrong password, but also a weak
    signal or a router that does not respond (tested: access point off, same
    prompt). Only WRONG_KEY really says the password is wrong."""
    import subprocess
    try:
        r = subprocess.run(["journalctl", "-q", "--no-pager", "-o", "cat", "-u", "wpa_supplicant",
                            "--since", "@%d" % int(since)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return "reason=WRONG_KEY" in r.stdout


def connect_wifi_outcome(ssid, password=None, is_hidden=False):
    """(ok, message, reason) — reason: None, "password", "not_found",
    "timeout", "other".

    The problem it solves: after a wrong password NetworkManager kept the
    network saved WITH the wrong password; from then on the interface treated
    it as "known", no longer asked for the password and kept retrying the
    wrong one. Now:
      - a new password always replaces the saved one;
      - if the connection fails, the profile is removed, so the next attempt
        asks for the password again (reason "password": the interface asks
        for it right away, without starting over);
      - "wrong password" is reported only if wpa_supplicant confirms it;
      - the password reaches nmcli through stdin (--ask), not the command
        line: it does not show up in the process list;
      - hidden networks are joined by name, with a "hidden" profile.
    """
    import time
    known = known_connection(ssid)
    dev = _wifi_dev()
    if not dev:
        return False, tr("This computer has no Wi-Fi adapter."), "other"
    if not is_hidden and not _wait_for_network(ssid):
        return False, tr("The network “{name}” is not in range").format(name=ssid), "not_found"
    start = time.time()
    if is_hidden:
        # it does not show up in scans, so "device wifi connect" cannot find
        # it even with "hidden yes" (tested): create the profile and activate
        # it; NetworkManager looks for it by name. With "wpa-psk" wpa_supplicant
        # also accepts WPA3 (it is given WPA-PSK and SAE together).
        if known:
            _nmcli(["connection", "delete", "id", ssid], timeout=15)
        security = ["wifi-sec.key-mgmt", "wpa-psk"] if password else []
        rc, out = _nmcli(["connection", "add", "type", "wifi", "ifname", dev, "con-name", ssid,
                          "ssid", ssid, "802-11-wireless.hidden", "yes"] + security, timeout=15)
        if rc != 0:
            return False, tr("Could not create the profile for “{name}”: {error}").format(
                name=ssid, error=out[-120:]), "other"
        known = False
        rc, out, reason = _activate_connection(["--ask", "connection", "up", "id", ssid], password)
    elif password:
        if known:
            _nmcli(["connection", "delete", "id", ssid], timeout=15)
        rc, out, reason = _activate_connection(["--ask", "device", "wifi", "connect", ssid, "ifname", dev], password)
    elif known:
        rc, out, reason = _activate_connection(["connection", "up", "id", ssid], None)
    else:
        # open network, or secured with no password given: with --ask nmcli
        # asks for it, and the empty answer makes it fail right away
        rc, out, reason = _activate_connection(["--ask", "device", "wifi", "connect", ssid, "ifname", dev], None)
    if rc == 0 and "error" not in out.lower():
        return True, tr("Connected to {name}").format(name=ssid), None
    reason = reason or _reason(out)
    if reason == "other" and "802-11-wireless-security" in out:
        reason = "password"                  # secured and no password given
    if is_hidden and reason == "not_found":
        reason = "timeout"                     # hidden: "not found" means it did not respond
    if reason == "password" and known_connection(ssid):
        _nmcli(["connection", "delete", "id", ssid], timeout=15)
    elif not known and reason != "timeout" and known_connection(ssid):
        _nmcli(["connection", "delete", "id", ssid], timeout=15)    # no half-made profiles
    if reason == "password" and ("property is invalid" in out.lower() or (password and len(password) < 8)):
        return False, tr("Invalid password for “{name}”: WPA networks need at least 8 characters.").format(
            name=ssid), reason
    if reason == "password" and not password:
        if known:
            return False, tr("The saved password for “{name}” no longer works: enter the current one.").format(
                name=ssid), reason
        return False, tr("“{name}” is secured: a password is required.").format(name=ssid), reason
    if reason == "password" and _key_rejected(start) is False:
        # NetworkManager asked for the password again, but the key was not
        # rejected: the connection failed for some other reason
        return False, tr("Could not join “{name}”. Check the password; if it is correct, the signal "
                         "is weak or the router did not respond: move closer and try again.").format(
                             name=ssid), reason
    last_line = out.splitlines()[-1][:120] if out else tr("unknown error")
    if reason == "password":
        msg = tr("Wrong password for “{name}”. Try again.").format(name=ssid)
    elif reason == "not_found":
        msg = tr("The network “{name}” is not in range").format(name=ssid)
    elif reason == "timeout":
        msg = tr("“{name}” did not respond in time: move closer to the router and try again").format(name=ssid)
    else:
        msg = tr("Connection failed: {error}").format(error=last_line)
    return False, msg, reason


def connect_wifi(ssid, password=None):
    """(ok, message) — see connect_wifi_outcome."""
    ok, msg, _m = connect_wifi_outcome(ssid, password)
    return ok, msg


def forget_wifi(ssid):
    """Forget a saved network (along with its password)."""
    rc, _out = _nmcli(["connection", "delete", "id", ssid], timeout=15)
    return rc == 0


def disconnect(device):
    run(NMCLI + ["device", "disconnect", device], timeout=15)


def vpns():
    """Configured VPN connections: [{name, uuid, type, active}]."""
    active = {row[0] for row in _rows(["-f", "UUID", "connection", "show", "--active"])}
    rows = []
    for name, uuid, typ in _rows(["-f", "NAME,UUID,TYPE", "connection", "show"]):
        if typ in VPN_TYPES:
            rows.append({"name": name, "uuid": uuid,
                         "type": "WireGuard" if typ == "wireguard" else "VPN",
                         "active": uuid in active})
    return rows


def set_vpn(uuid, on):
    out = run(["nmcli", "connection", "up" if on else "down", "uuid", uuid], timeout=40, check=True)
    return out is not None


def import_vpn(path):
    """Import a .conf (WireGuard) or .ovpn (OpenVPN) file. (ok, message)."""
    kind = "wireguard" if path.lower().endswith(".conf") else "openvpn"
    out = run(["nmcli", "connection", "import", "type", kind, "file", path], timeout=20, check=True)
    if out is None:
        return False, tr("Import failed (invalid file?)")
    return True, tr("VPN imported")


def remove_connection(uuid):
    return run(["nmcli", "connection", "delete", "uuid", uuid], timeout=15, check=True) is not None


# ---------------- proxy ----------------
# The system proxy is the desktop one (org.gnome.system.proxy), read by
# Firefox and GTK apps; the same value goes into environment variables
# (~/.config/environment.d/zeta-proxy.conf) for terminal programs.
ENV_FILE = os.path.expanduser("~/.config/environment.d/zeta-proxy.conf")


def _gs(*args):
    return (run(["gsettings"] + list(args)) or "").strip().strip("'")


def proxy():
    mode = _gs("get", "org.gnome.system.proxy", "mode") or "none"
    host = _gs("get", "org.gnome.system.proxy.http", "host")
    port = _gs("get", "org.gnome.system.proxy.http", "port")
    url = _gs("get", "org.gnome.system.proxy", "autoconfig-url")
    return {"mode": mode, "host": host, "port": int(port) if port.isdigit() else 0, "url": url}


def set_proxy(mode, host="", port=0, url=""):
    run(["gsettings", "set", "org.gnome.system.proxy", "mode", mode])
    if mode == "manual":
        for scheme in ("http", "https"):
            run(["gsettings", "set", "org.gnome.system.proxy." + scheme, "host", host])
            run(["gsettings", "set", "org.gnome.system.proxy." + scheme, "port", str(int(port or 0))])
    if mode == "auto":
        run(["gsettings", "set", "org.gnome.system.proxy", "autoconfig-url", url])
    os.makedirs(os.path.dirname(ENV_FILE), exist_ok=True)
    if mode == "manual" and host:
        p = "http://%s:%d/" % (host, int(port or 0))
        with open(ENV_FILE, "w") as f:
            f.write("# Written by ZETA RAYS Settings\n")
            for v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
                f.write("%s=%s\n" % (v, p))
            f.write("no_proxy=localhost,127.0.0.1,::1\n")
    elif os.path.exists(ENV_FILE):
        os.remove(ENV_FILE)


def proxy_env():
    """Proxy as seen by programs (environment variables)."""
    return {k: v for k, v in os.environ.items() if k.lower() in ("http_proxy", "https_proxy", "all_proxy")}


def public_ip_local():
    """Local IPs per interface (no external requests)."""
    out = run(["ip", "-o", "-4", "addr", "show", "scope", "global"])
    return re.findall(r"^\d+:\s+(\S+)\s+inet\s+([\d.]+)", out or "", re.M)
