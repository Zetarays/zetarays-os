# SPDX-License-Identifier: GPL-3.0-or-later
"""Honest, calm state of the system services.

One place decides how a failed systemd service is reported: the Monitor
(header, Services and Security pages), the health check (zeta-health),
"zeta system", zeta-selftest and zeta-diagnostics all use it.

Four levels:
  normal   nothing to report
  info     worth knowing, no action needed (a service for hardware this
           computer does not have, a service that is no longer installed)
  warning  a real condition that may need attention (a scheduled job failed
           once and will run again by itself)
  error    a confirmed significant problem (a service is not working)

The verdict comes from evidence, never from a wish to hide a problem:
  - the unit's properties (`systemctl show`): Result, ExecMainStatus,
    ExecMainCode, timestamps, TriggeredBy, Type, UnitFileState, ...
  - the unit's last log lines (journal) and systemd's own messages about it
  - the next run of the timer that starts it
A failed unit stays an error unless the evidence clearly says otherwise.
systemd keeps "failed" only until the next start, so a unit that is not in
the failed state any more (it recovered, or someone ran reset-failed) is
simply not reported.

Nothing in here changes the system. "Try again" and "Dismiss" are run by the
Monitor through its privileged helper, and only when the user asks.

Command line (read-only):
  python3 unitstate.py --report   every failed service: verdict, details and
                                  the last 20 log lines (for zeta-diagnostics)
  python3 unitstate.py --health   one tab-separated line per failed service
                                  (level, unit, failure time, title, why), for zeta-health
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, "/usr/lib/zeta")
from i18n import ntr, tr  # noqa: E402

NORMAL, INFO, WARNING, ERROR = "normal", "info", "warning", "error"
LEVELS = (NORMAL, INFO, WARNING, ERROR)
RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

# A scheduled job that failed this many times in a row is no longer a
# one-off: it becomes an error.
REPEATED_FAILURES = 3

SHOW_PROPS = ("Id", "Description", "LoadState", "ActiveState", "SubState", "Result",
              "ExecMainStatus", "ExecMainCode", "ExecMainExitTimestamp", "ActiveEnterTimestamp",
              "InactiveExitTimestamp", "InactiveEnterTimestamp", "TriggeredBy", "Type",
              "UnitFileState", "NRestarts", "CanStart", "RefuseManualStart")

# Same rule as in /usr/libexec/zeta-monitor-helper (keep them in sync): a
# service name, never an option or a path.
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@:._\\-]{0,250}\.service$")

HELPER = "/usr/libexec/zeta-monitor-helper"


def valid_unit(name):
    return bool(UNIT_RE.match(name or ""))


# ------------------------------------------------------------------ evidence
# Services that fail only because the hardware they serve is not in this
# computer. A unit is "not used on this computer" ONLY when its name matches
# AND its own log lines contain one of these messages (the exact text the
# program writes when the device is missing). Anything else stays an error.
# (unit name patterns, journal evidence, explanation key)
HARDWARE_PATTERNS = (
    # systemd-backlight: no built-in panel (desktop or Mini PC on HDMI)
    (("systemd-backlight@*.service",),
     r"Failed to get backlight or LED device|No such device", "backlight"),
    # smartd: no disk that reports SMART (virtual disks, some USB enclosures)
    (("smartd.service", "smartmontools.service"),
     r"Unable to monitor any SMART enabled devices|No devices to monitor|DEVICESCAN failed", "smart"),
    # ModemManager: no mobile broadband modem
    (("ModemManager.service",), r"\b[Nn]o modems? (were )?(found|available|detected)", "modem"),
    # BlueZ and its helpers: no Bluetooth adapter
    (("bluetooth.service", "hciuart.service", "bthelper@*.service"),
     r"[Nn]o (default )?(Bluetooth )?(adapter|controller)s? (found|available|present)"
     r"|hci\d+.*No such device", "bluetooth"),
    # NVIDIA services without an NVIDIA card or driver
    (("nvidia-*.service",),
     r"NVIDIA driver (is )?not (found|loaded|installed)|No NVIDIA (GPU|device)s? (found|detected|present)"
     r"|Failed to (query|open) NVIDIA devices?|/dev/nvidia\S*: No such file"
     r"|NVIDIA-SMI has failed|No devices were found|Failed to initialize NVML", "nvidia"),
    # AMD compute services without an AMD graphics card
    (("amd*.service", "rocm*.service"),
     r"No AMD (GPU|graphics)|/dev/kfd.*No such file|amdgpu.*(not found|No such device)", "amd"),
    # thermald: only for some Intel processors
    (("thermald.service",), r"Unsupported (cpu model|CPU|platform)|No coretemp sysfs", "thermald"),
    # ALSA state: no sound card
    (("alsa-restore.service", "alsa-state.service"), r"No soundcards found|[Cc]annot find card", "sound"),
    # lm-sensors: no readable sensor
    (("lm-sensors.service",), r"No sensors found", "sensors"),
    # virtual machine helpers on a real computer
    (("open-vm-tools.service", "vgauth.service", "vmtoolsd.service", "virtualbox-guest-utils.service",
      "vboxadd*.service", "qemu-guest-agent.service", "spice-vdagentd.service", "hv-*.service",
      "hyperv-*.service"),
     r"[Nn]ot running (in|inside) a (virtual machine|VM)|[Nn]ot (running )?(on|in) (a )?VMware"
     r"|Failed to open /dev/(vboxguest|vmci|virtio-ports)|vboxguest.*(not found|No such device)"
     r"|org\.qemu\.guest_agent\.0.*No such file|[Nn]o (Hyper-V|VMBus)", "vm"),
)

def _hardware_text(key):
    # one sentence per HARDWARE_PATTERNS key
    return {
        "backlight": tr("This computer has no built-in screen whose brightness the system can save, "
                        "so this service has nothing to do."),
        "smart": tr("No disk in this computer reports its health (SMART), so there is nothing to watch."),
        "modem": tr("This computer has no mobile broadband modem."),
        "bluetooth": tr("This computer has no Bluetooth adapter."),
        "nvidia": tr("This computer has no NVIDIA graphics card, so this service has nothing to do."),
        "amd": tr("This computer has no AMD graphics card for this service."),
        "thermald": tr("This service only works with some Intel processors, not with this one."),
        "sound": tr("This computer has no sound card for this service."),
        "sensors": tr("This computer has no hardware sensors that can be read."),
        "vm": tr("This is a real computer, not a virtual machine, so the virtual machine helper "
                 "has nothing to do."),
    }.get(key, "")


# Services whose only job is to make startup wait for the network.
WAIT_ONLINE = ("NetworkManager-wait-online.service", "systemd-networkd-wait-online.service",
               "systemd-networkd-wait-online@*.service")


def hardware_evidence(unit, journal):
    """Key of the matching hardware pattern, or None. Both the unit name and
    one of its own log lines must match."""
    text = "\n".join(journal or ())
    for globs, pattern, key in HARDWARE_PATTERNS:
        if any(fnmatch.fnmatchcase(unit, g) for g in globs) and re.search(pattern, text):
            return key
    return None


# --------------------------------------------------------------- plain words
def friendly_name(props):
    """A name a person understands: known services by what they do, the
    others by the description their package gives them."""
    unit = props.get("Id", "")
    base = unit[:-8] if unit.endswith(".service") else unit
    stem = base.split("@", 1)[0] + ("@" if "@" in base else "")
    known = {
        "chkrootkit": tr("Daily security scan"),
        "lynis": tr("Security audit"),
        "rkhunter": tr("Rootkit scan"),
        "clamav-freshclam": tr("Antivirus updates"),
        "clamav-daemon": tr("Antivirus"),
        "apt-daily": tr("Update check"),
        "apt-daily-upgrade": tr("Automatic updates"),
        "man-db": tr("Manual pages index"),
        "plocate-updatedb": tr("File search index"),
        "dpkg-db-backup": tr("Package list backup"),
        "logrotate": tr("Log cleanup"),
        "e2scrub_all": tr("Disk check"),
        "e2scrub_reap": tr("Disk check"),
        "fstrim": tr("SSD maintenance"),
        "zeta-health": tr("Health check"),
        "ollama": tr("Local AI"),
        "NetworkManager": tr("Network"),
        "NetworkManager-wait-online": tr("Wait for the network at startup"),
        "systemd-networkd-wait-online": tr("Wait for the network at startup"),
        "wpa_supplicant": "Wi-Fi",
        "ModemManager": tr("Mobile broadband"),
        "bluetooth": "Bluetooth",
        "cups": tr("Printers"),
        "cups-browsed": tr("Network printer discovery"),
        "avahi-daemon": tr("Local network discovery"),
        "ssh": tr("Remote access (SSH)"),
        "nftables": "Firewall",
        "ufw": "Firewall",
        "earlyoom": tr("Memory protection"),
        "zramswap": tr("Compressed memory"),
        "sddm": tr("Login screen"),
        "systemd-backlight@": tr("Screen brightness"),
        "thermald": tr("Temperature control"),
        "smartd": tr("Disk health monitoring"),
        "smartmontools": tr("Disk health monitoring"),
        "open-vm-tools": tr("VMware helper"),
        "virtualbox-guest-utils": tr("VirtualBox helper"),
        "qemu-guest-agent": tr("QEMU helper"),
        "spice-vdagentd": tr("Virtual machine display helper"),
        "systemd-timesyncd": tr("Clock synchronization"),
        "apparmor": tr("App protection (AppArmor)"),
        "zeta-ssh-sync": tr("Remote access setting in the firewall"),
        "zeta-vm-sleep": tr("Virtual machine setup"),
        "zeta-live-password": tr("Live session setup"),
    }
    return known.get(base) or known.get(stem) or props.get("Description") or base


def cause_text(props):
    """Why it stopped, in plain words, from Result and the exit status."""
    result = props.get("Result", "")
    code = props.get("ExecMainCode", "")        # 1 exited, 2 killed, 3 dumped
    try:
        status = int(props.get("ExecMainStatus") or 0)
    except ValueError:
        status = 0
    if result == "timeout":
        return tr("It took too long and was stopped.")
    if result == "oom-kill":
        return tr("It was closed because the memory ran out.")
    if result == "start-limit-hit":
        return tr("It failed several times in a row, so the system stopped retrying.")
    if result == "resources":
        return tr("The system could not prepare what it needs to start (a missing file, folder or account).")
    if result == "watchdog":
        return tr("It stopped responding.")
    if result == "core-dump" or (result != "exit-code" and code == "3"):
        return tr("It crashed.")
    if result == "signal" or (result != "exit-code" and code == "2"):
        return tr("It was stopped unexpectedly.")
    if result == "exit-code" or code == "1":
        if status == 127:
            return tr("A program it needs is missing.")
        if status == 126:
            return tr("A program it needs cannot be run.")
        if status == 203:
            return tr("Its program could not be started.")
        if 200 <= status <= 245:
            return tr("The system could not set it up to start (code {code}).").format(code=status)
        if status:
            return tr("It ended with an error (code {code}).").format(code=status)
    return tr("It stopped with an error.")


def when_text(ts, now=None):
    """'today at 14:00', 'tomorrow at 03:10' or 'on 10/18 at 03:10'."""
    now = time.time() if now is None else now
    t, n = time.localtime(ts), time.localtime(now)
    clock = time.strftime("%H:%M", t)
    days = (time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
            - time.mktime((n.tm_year, n.tm_mon, n.tm_mday, 0, 0, 0, 0, 0, -1))) / 86400.0
    if round(days) == 0:
        return tr("today at {time}").format(time=clock)
    if round(days) == 1:
        return tr("tomorrow at {time}").format(time=clock)
    return tr("on {month}/{day} at {time}").format(month="%02d" % t.tm_mon, day="%02d" % t.tm_mday, time=clock)


# ------------------------------------------------------------ classification
def ts(value):
    """Seconds since the epoch from a `systemctl show` timestamp: "@1792222910"
    (--timestamp=unix) or "Sat 2026-10-17 07:41:50 UTC". 0 when empty."""
    value = (value or "").strip()
    if not value or value == "n/a":
        return 0.0
    if value.startswith("@"):
        try:
            return float(value[1:])
        except ValueError:
            return 0.0
    m = re.search(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", value)
    if not m:
        return 0.0
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


_FAIL_RE = re.compile(r"Failed with result '")
_OK_RE = re.compile(r"Deactivated successfully|^Finished ")


def run_history(history):
    """(consecutive failures at the end, outcome of the last run) from
    systemd's own messages about the unit (journalctl _PID=1 UNIT=...).
    outcome: "failed", "ok" or None when the log says nothing."""
    failures, outcome = 0, None
    for line in reversed(list(history or ())):
        if _FAIL_RE.search(line):
            failures += 1
            outcome = outcome or "failed"
        elif _OK_RE.search(line):
            outcome = outcome or "ok"
            break
    return failures, outcome


def classify_service(props):
    """Short state of any service (the Services table). Unchanged meaning:
    RUNNING, DONE, STOPPED, NOT_APPLICABLE, WARNING (failed, started by a
    timer), FAILED. A failed unit gets its real verdict from assess()."""
    active = props.get("ActiveState", "")
    sub = props.get("SubState", "")
    if active == "failed" or sub == "failed":
        # a job started by a timer that failed is a warning, not a broken system
        return "WARNING" if ".timer" in props.get("TriggeredBy", "") else "FAILED"
    if sub == "running":
        return "RUNNING"
    if active == "active":
        return "DONE"
    evaluated = props.get("ConditionTimestampMonotonic", "0") not in ("", "0")
    if evaluated and props.get("ConditionResult") == "no":
        return "NOT_APPLICABLE"
    return "STOPPED"


def assess(props, journal=(), history=(), next_runs=None, network_up=None, now=None):
    """Verdict on one service.

    props       `systemctl show` properties (SHOW_PROPS)
    journal     its last log lines (journalctl -u UNIT -n 20 -o cat)
    history     systemd's messages about it (journalctl _PID=1 UNIT=UNIT -o cat)
    next_runs   {timer: next run, seconds since the epoch (0 = not scheduled)}
    network_up  True/False/None (unknown): is there a network route now
    """
    now = time.time() if now is None else now
    unit = props.get("Id", "")
    name = friendly_name(props)
    v = {"unit": unit, "name": name, "description": props.get("Description") or unit,
         "level": NORMAL, "kind": "ok", "title": "", "explanation": "",
         "next_run": 0, "failures": 0, "actions": [], "evidence": "",
         "since": ts(props.get("InactiveEnterTimestamp")),
         "props": {k: props.get(k, "") for k in SHOW_PROPS},
         "journal": [line for line in (journal or ())][-20:]}

    # --- not failed (any more): nothing to report
    if props.get("ActiveState") != "failed":
        return v
    # failed, but it became active after the failure, or systemd's own log
    # says the last run went well: the "failed" we read is out of date
    if ts(props.get("ActiveEnterTimestamp")) > v["since"] > 0:
        v["kind"] = "stale"
        return v
    failures, outcome = run_history(history)
    if outcome == "ok":
        v["kind"] = "stale"
        return v
    v["failures"] = max(1, failures)
    retry_ok = props.get("CanStart", "yes") != "no" and props.get("RefuseManualStart", "no") != "yes"

    def done(level, kind, title, explanation, actions):
        v.update(level=level, kind=kind, title=title, explanation=explanation, actions=actions)
        return v

    # --- left over from a service that is gone or switched off
    load = props.get("LoadState", "loaded")
    if load in ("not-found", "masked"):
        return done(INFO, "removed", tr("No longer in use: {name}").format(name=name),
                    tr("This service is no longer installed or has been switched off. "
                       "Its last error is left over from before.") if load == "not-found" else
                    tr("This service has been switched off. Its last error is left over from before."),
                    ["dismiss"])

    # --- hardware that is not in this computer (pattern + log evidence)
    hw = hardware_evidence(unit, v["journal"])
    if hw:
        v["evidence"] = hw
        return done(INFO, "hardware", tr("Not used on this computer: {name}").format(name=name),
                    _hardware_text(hw), ["dismiss"])

    # --- startup gave up waiting for the network
    if any(fnmatch.fnmatchcase(unit, g) for g in WAIT_ONLINE):
        if network_up:
            return done(INFO, "network-late", tr("The network was not ready at startup"),
                        tr("Startup stopped waiting for the network, which connected later. "
                           "Nothing needs to be done."), ["dismiss"])
        return done(WARNING, "network-missing", tr("The network was not ready at startup"),
                    tr("Startup stopped waiting for the network, and there is no connection now."),
                    (["retry"] if retry_ok else []) + ["dismiss"])

    cause = cause_text(props)
    # --- a scheduled job (started by a timer)
    timers = [t for t in props.get("TriggeredBy", "").split() if t.endswith(".timer")]
    if timers:
        nexts = [n for n in ((next_runs or {}).get(t, 0) for t in timers) if n and n > now]
        v["next_run"] = min(nexts) if nexts else 0
        if v["failures"] >= REPEATED_FAILURES:
            return done(ERROR, "periodic-repeated", tr("A scheduled task keeps failing: {name}").format(name=name),
                        cause + " " + ntr("It failed {n} time in a row.", "It failed {n} times in a row.",
                                          v["failures"]).format(n=v["failures"]),
                        (["retry"] if retry_ok else []) + ["dismiss"])
        if v["next_run"]:
            return done(WARNING, "periodic", tr("A scheduled task failed: {name}").format(name=name),
                        cause + " " + tr("It will run again automatically {when}.").format(
                            when=when_text(v["next_run"], now)),
                        (["retry"] if retry_ok else []) + ["dismiss"])
        return done(ERROR, "periodic-unscheduled", tr("A scheduled task failed: {name}").format(name=name),
                    cause + " " + tr("It is not scheduled to run again."),
                    (["retry"] if retry_ok else []) + ["dismiss"])

    # --- everything else: a real failure
    title = (tr("A background task failed: {name}") if props.get("Type") == "oneshot"
             else tr("A background service stopped working: {name}")).format(name=name)
    return done(ERROR, "failed", title, cause, (["retry"] if retry_ok else []) + ["dismiss"])


def details_text(v):
    """Technical details (the "Details" expander and zeta-diagnostics)."""
    p = v.get("props", {})
    lines = ["%s: %s" % (tr("Service"), v.get("unit", "")),
             "%s: %s" % (tr("Description"), p.get("Description", "") or "-")]
    status = p.get("ExecMainStatus", "")
    code = {"1": "exited", "2": "killed", "3": "dumped"}.get(p.get("ExecMainCode", ""), p.get("ExecMainCode", ""))
    lines.append("Result=%s  ExecMainStatus=%s  ExecMainCode=%s  Type=%s" % (
        p.get("Result", ""), status, code, p.get("Type", "")))
    lines.append("TriggeredBy=%s  UnitFileState=%s  LoadState=%s  NRestarts=%s" % (
        p.get("TriggeredBy", "") or "-", p.get("UnitFileState", "") or "-", p.get("LoadState", ""),
        p.get("NRestarts", "") or "0"))
    if v.get("since"):
        lines.append("%s: %s" % (tr("Failed at"), time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v["since"]))))
    if v.get("next_run"):
        lines.append("%s: %s" % (tr("Next run"), time.strftime("%Y-%m-%d %H:%M:%S",
                                                               time.localtime(v["next_run"]))))
    lines.append("%s: %s / %s%s" % (tr("Verdict"), v.get("level", "").upper(), v.get("kind", ""),
                                    (" (%s)" % v["evidence"]) if v.get("evidence") else ""))
    journal = v.get("journal") or []
    lines.append("")
    lines.append(tr("Last log lines:") if journal else
                 tr("No log lines readable (run as administrator to see them)."))
    lines.extend(journal)
    return "\n".join(lines)


# ------------------------------------------------------------------ collection
def _run(cmd, timeout=6):
    """(exit code, stdout). The output is parsed: C locale."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C", SYSTEMD_COLORS="0", SYSTEMD_PAGER=""))
        return p.returncode, p.stdout
    except (subprocess.SubprocessError, OSError):
        return 1, ""


def parse_show(text):
    """`systemctl show` output (blocks separated by a blank line) -> [dict]."""
    out = []
    for block in (text or "").split("\n\n"):
        props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if props.get("Id"):
            out.append(props)
    return out


def read_failed():
    """Properties of every service that is in the failed state right now."""
    base = ["systemctl", "show", "--state=failed", "--type=service", "--no-pager",
            "-p", ",".join(SHOW_PROPS)]
    rc, out = _run(base[:2] + ["--timestamp=unix"] + base[2:] + ["*"])
    if rc != 0 and not out.strip():      # older systemctl without --timestamp
        rc, out = _run(base + ["*"])
    return [p for p in parse_show(out) if p["Id"].endswith(".service") and p.get("ActiveState") == "failed"]


def read_next_runs():
    """{timer: next run in seconds since the epoch, 0 = not scheduled}."""
    _, out = _run(["systemctl", "list-timers", "--all", "--output=json", "--no-pager"])
    runs = {}
    try:
        for t in json.loads(out or "[]"):
            runs[t.get("unit", "")] = (t.get("next") or 0) / 1e6
    except (ValueError, TypeError, AttributeError):
        pass
    return runs


def read_logs(unit, lines=20):
    """(last log lines of the unit in this boot, systemd's messages about it
    in every boot: a scheduled job that kept failing across restarts counts)."""
    _, journal = _run(["journalctl", "-b", "-u", unit, "-n", str(lines), "-o", "cat", "--no-pager", "-q"])
    _, history = _run(["journalctl", "_PID=1", "UNIT=" + unit, "-n", "40", "-o", "cat", "--no-pager", "-q"])
    return journal.splitlines(), history.splitlines()


def read_logs_privileged():
    """Logs of all failed services through the helper (administrators, no
    password: see /etc/sudoers.d/zeta-monitor). {} if not allowed."""
    rc, out = _run(["sudo", "-n", HELPER, "failed-logs"], timeout=12)
    try:
        data = json.loads(out) if rc == 0 and out.strip() else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def network_up():
    """True if there is a default route (IPv4 or IPv6)."""
    try:
        with open("/proc/net/route") as f:
            if any(line.split()[1:2] == ["00000000"] for line in f.readlines()[1:]):
                return True
    except OSError:
        pass
    try:
        with open("/proc/net/ipv6_route") as f:
            for line in f:
                parts = line.split()
                if parts and parts[0] == "0" * 32 and parts[1] == "00" and parts[-1] != "lo":
                    return True
    except OSError:
        pass
    return False


# Logs read for one failure instance (unit, failure time): read again only
# when the unit fails again. The verdict itself is recomputed on every call.
_LOG_CACHE = {}


def failed_verdicts(include_normal=False):
    """Verdicts on every failed service, the most serious first. Read-only."""
    units = read_failed()
    if not units:
        return []
    now = time.time()
    next_runs = read_next_runs() if any(".timer" in p.get("TriggeredBy", "") for p in units) else {}
    net = network_up() if any(fnmatch.fnmatchcase(p["Id"], g) for p in units for g in WAIT_ONLINE) else None
    keys = {p["Id"]: (p["Id"], p.get("InactiveEnterTimestamp", "")) for p in units}
    missing = [u for u, k in keys.items() if k not in _LOG_CACHE]
    for unit in missing:
        _LOG_CACHE[keys[unit]] = read_logs(unit)
    if any(not _LOG_CACHE[keys[u]][0] for u in missing) and os.geteuid() != 0:
        # not readable as this user (not in the adm group): ask the helper
        for unit, logs in read_logs_privileged().items():
            if unit in keys and isinstance(logs, dict) and not _LOG_CACHE[keys[unit]][0]:
                _LOG_CACHE[keys[unit]] = ([str(x) for x in logs.get("journal", [])][-20:],
                                          [str(x) for x in logs.get("history", [])][-40:])
    for k in [k for k in _LOG_CACHE if k not in keys.values()]:
        del _LOG_CACHE[k]
    out = []
    for p in units:
        journal, history = _LOG_CACHE.get(keys[p["Id"]], ([], []))
        v = assess(p, journal, history, next_runs, net, now)
        if include_normal or v["level"] != NORMAL:
            out.append(v)
    out.sort(key=lambda v: (-RANK[v["level"]], v["name"].lower()))
    return out


def worst(verdicts):
    return max((v["level"] for v in verdicts), key=RANK.get, default=NORMAL)


# -------------------------------------------------------------- command line
def _report():
    verdicts = failed_verdicts(include_normal=True)
    if not verdicts:
        print(tr("No failed services."))
        return
    for v in verdicts:
        if v["level"] == NORMAL:
            print("[%s] %s: %s" % (v["level"].upper(), v["unit"],
                                   tr("no longer failed (out of date), not shown")))
            continue
        print("[%s] %s" % (v["level"].upper(), v["title"]))
        print("    " + v["explanation"])
        for line in details_text(v).splitlines():
            print("    " + line)
        print()


def _health():
    for v in failed_verdicts():
        print("\t".join([v["level"], v["unit"], "%d" % v["since"],
                         v["title"].replace("\t", " "), v["explanation"].replace("\t", " ")]))


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--report"
    if arg == "--health":
        _health()
    elif arg == "--report":
        _report()
    else:
        sys.stderr.write("usage: unitstate.py [--report|--health]\n")
        sys.exit(2)
