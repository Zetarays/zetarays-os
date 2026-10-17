# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Monitor — data collectors (native, local-first).

Every function collects real data and handles absence (permissions, missing
sensor, missing command) by returning "N/A" values instead of raising
exceptions. No data is sent anywhere, except for IP geolocation (explicit,
can be turned off).

Uses `psutil` where available and native interfaces (/proc, ss, systemctl, nft).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "/usr/lib/zeta")
from i18n import tr, trc  # noqa: E402

try:
    import psutil
except ImportError:  # degrade without crashing
    psutil = None

NA = "N/A"


def _run(cmd, timeout=4.0, c_locale=False):
    # c_locale: the output is parsed, so it must not depend on the user's language
    env = dict(os.environ, LC_ALL="C") if c_locale else None
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.stdout
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def _fmt_bytes(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return NA
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.1f %s" % (n, unit)
        n /= 1024


def fmt_rate(n):
    return _fmt_bytes(n) + "/s" if n != NA else NA


def short_datetime(ts):
    """Day, month and time, in the order the user's language expects."""
    t = time.localtime(ts)
    return tr("{month}/{day} {time}").format(month="%02d" % t.tm_mon, day="%02d" % t.tm_mday,
                                            time=time.strftime("%H:%M", t))


# The state of services is decided in one place (unitstate.py), shared with
# zeta-health, "zeta system", zeta-selftest and zeta-diagnostics.
from monitor.unitstate import classify_service, failed_verdicts  # noqa: E402,F401


def failed_services():
    """(errors, warnings): names of the failed services that are a confirmed
    problem, and of those that only need attention (see unitstate.assess)."""
    verdicts = failed_verdicts()
    return ([v["unit"][:-8] for v in verdicts if v["level"] == "error"],
            [v["unit"][:-8] for v in verdicts if v["level"] == "warning"])


class Collectors:
    """Stateful collection, to compute rates (network, disk, per-process CPU)."""

    def __init__(self):
        self._net_prev = None
        self._disk_prev = None
        self._proc_primed = False
        self.geo_enabled = True

    # ---------------- system ----------------
    def system(self):
        info = {"host": socket.gethostname(), "os": NA, "kernel": NA,
                "uptime": NA, "cpu_temp": NA, "load": NA, "arch": NA}
        try:
            with open("/etc/os-release") as f:
                d = dict(line.strip().split("=", 1) for line in f if "=" in line)
            info["os"] = d.get("PRETTY_NAME", "ZETA RAYS OS").strip('"')
        except OSError:
            info["os"] = "ZETA RAYS OS"
        info["kernel"] = "Linux " + os.uname().release.split("+")[0].split("-")[0]
        info["arch"] = os.uname().machine
        try:
            with open("/proc/uptime") as f:
                up = float(f.read().split()[0])
            h = int(up // 3600); m = int((up % 3600) // 60); s = int(up % 60)
            info["uptime"] = "%02d:%02d:%02d" % (h, m, s)
        except (OSError, ValueError):
            pass
        try:
            la = os.getloadavg()
            info["load"] = "%.2f %.2f %.2f" % la
        except OSError:
            pass
        info["cpu_temp"] = self.cpu_temp()
        return info

    def cpu_temp(self):
        if not psutil or not hasattr(psutil, "sensors_temperatures"):
            return NA
        try:
            temps = psutil.sensors_temperatures()
        except Exception:  # noqa: BLE001
            return NA
        for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if key in temps and temps[key]:
                return "%.0f °C" % temps[key][0].current
        for arr in temps.values():
            if arr:
                return "%.0f °C" % arr[0].current
        return NA

    # ---------------- CPU / memory / disk ----------------
    def cpu(self):
        if not psutil:
            return {"total": NA, "per_core": [], "freq": NA}
        total = psutil.cpu_percent(interval=None)
        cores = psutil.cpu_percent(interval=None, percpu=True)
        freq = NA
        try:
            f = psutil.cpu_freq()
            if f:
                freq = "%.0f MHz" % f.current
        except Exception:  # noqa: BLE001
            pass
        return {"total": total, "per_core": cores, "freq": freq}

    def memory(self):
        if not psutil:
            return {}
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        return {"total": vm.total, "used": vm.used, "available": vm.available,
                "cached": getattr(vm, "cached", 0), "percent": vm.percent,
                "swap_total": sm.total, "swap_used": sm.used, "swap_percent": sm.percent}

    # ---------------- GPU ----------------
    _VENDOR = {"0x8086": "Intel", "0x1002": "AMD", "0x10de": "NVIDIA",
               "0x15ad": tr("VMware (virtual)"), "0x1af4": tr("Virtio (virtual)"),
               "0x80ee": tr("VirtualBox (virtual)"), "0x1234": tr("QEMU (virtual)")}

    def gpu(self):
        """GPU usage, where the driver makes it measurable without privileges.

        AMD reports usage directly; for Intel it is derived from the time spent
        idle (RC6): 100% minus the idle share. Where there is no way to measure
        it we say "not measurable" instead of making up a number.
        """
        import glob
        out = {"name": NA, "driver": NA, "busy": None, "vram_used": None,
               "vram_total": None, "freq": None}
        for card in sorted(glob.glob("/sys/class/drm/card[0-9]")):
            dev = os.path.join(card, "device")
            try:
                vendor = open(os.path.join(dev, "vendor")).read().strip()
            except OSError:
                continue
            out["name"] = self._VENDOR.get(vendor, vendor)
            try:
                out["driver"] = os.path.basename(os.readlink(os.path.join(dev, "driver")))
            except OSError:
                pass

            def read(*pieces):
                try:
                    with open(os.path.join(*pieces)) as f:
                        return f.read().strip()
                except OSError:
                    return None
            busy = read(dev, "gpu_busy_percent")                    # AMD
            if busy is not None and busy.isdigit():
                out["busy"] = float(busy)
            vu, vt = read(dev, "mem_info_vram_used"), read(dev, "mem_info_vram_total")
            if vu and vt and vu.isdigit() and vt.isdigit():
                out["vram_used"], out["vram_total"] = int(vu), int(vt)
            rc6 = read(card, "power", "rc6_residency_ms")            # Intel i915
            if rc6 is None:
                rc6 = read(dev, "tile0", "gt0", "gtidle", "idle_residency_ms")  # Intel xe
            if rc6 is not None and rc6.isdigit() and out["busy"] is None:
                now = time.monotonic()
                prev = getattr(self, "_rc6_prev", None)
                self._rc6_prev = (now, int(rc6))
                if prev and now > prev[0]:
                    idle = (int(rc6) - prev[1]) / ((now - prev[0]) * 1000.0)
                    out["busy"] = max(0.0, min(100.0, 100.0 * (1.0 - idle)))
            f = read(card, "gt_act_freq_mhz") or read(card, "gt_cur_freq_mhz")
            if f and f.isdigit():
                out["freq"] = int(f)
            if vendor == "0x10de" and shutil.which("nvidia-smi"):
                r = _run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                          "--format=csv,noheader,nounits"], timeout=3)
                try:
                    u, mu, mt = [float(x) for x in (r or "").splitlines()[0].split(",")]
                    out["busy"], out["vram_used"], out["vram_total"] = u, mu * 2**20, mt * 2**20
                except (ValueError, IndexError):
                    pass
            break
        return out

    def storage(self):
        out = {"parts": [], "read_rate": NA, "write_rate": NA}
        if not psutil:
            return out
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
                out["parts"].append({"device": p.device, "mount": p.mountpoint,
                                     "fstype": p.fstype, "total": u.total,
                                     "used": u.used, "free": u.free, "percent": u.percent})
            except (PermissionError, OSError):
                continue
        try:
            io = psutil.disk_io_counters()
            now = time.time()
            if io and self._disk_prev:
                pio, pt = self._disk_prev
                dt = max(1e-3, now - pt)
                out["read_rate"] = (io.read_bytes - pio.read_bytes) / dt
                out["write_rate"] = (io.write_bytes - pio.write_bytes) / dt
            self._disk_prev = (io, now)
        except Exception:  # noqa: BLE001
            pass
        return out

    # ---------------- network ----------------
    def net_io(self):
        """In/out rates and totals. Rates in bytes/s (None on the first pass)."""
        out = {"in_rate": None, "out_rate": None, "in_pps": None, "out_pps": None,
               "total_in": NA, "total_out": NA}
        if not psutil:
            return out
        io = psutil.net_io_counters()
        now = time.time()
        out["total_in"] = io.bytes_recv
        out["total_out"] = io.bytes_sent
        if self._net_prev:
            pio, pt = self._net_prev
            dt = max(1e-3, now - pt)
            out["in_rate"] = (io.bytes_recv - pio.bytes_recv) / dt
            out["out_rate"] = (io.bytes_sent - pio.bytes_sent) / dt
            out["in_pps"] = (io.packets_recv - pio.packets_recv) / dt
            out["out_pps"] = (io.packets_sent - pio.packets_sent) / dt
        self._net_prev = (io, now)
        return out

    def interfaces(self):
        rows = []
        if not psutil:
            return rows
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, al in addrs.items():
            if name == "lo":
                continue
            ip4 = ip6 = mac = NA
            for a in al:
                if a.family == socket.AF_INET:
                    ip4 = a.address
                elif a.family == socket.AF_INET6:
                    ip6 = a.address.split("%")[0]
                elif getattr(socket, "AF_PACKET", None) and a.family == socket.AF_PACKET:
                    mac = a.address
            st = stats.get(name)
            rows.append({"name": name, "ipv4": ip4, "ipv6": ip6, "mac": mac,
                         "up": bool(st and st.isup),
                         "speed": ("%d Mb/s" % st.speed) if (st and st.speed) else NA})
        return rows

    def gateway_dns(self):
        gw = NA
        r = _run(["ip", "route", "show", "default"])
        m = re.search(r"default via (\S+)", r)
        if m:
            gw = m.group(1)
        dns = []
        try:
            with open("/etc/resolv.conf") as f:
                for line in f:
                    if line.startswith("nameserver"):
                        dns.append(line.split()[1])
        except OSError:
            pass
        if not dns:
            r = _run(["resolvectl", "dns"])
            dns = re.findall(r"(\d+\.\d+\.\d+\.\d+)", r)
        return {"gateway": gw, "dns": dns or [NA]}

    def public_ip_geo(self):
        """IP geolocation (EXTERNAL). Only if enabled. None if unavailable."""
        if not self.geo_enabled:
            return None
        try:
            req = urllib.request.Request("https://ipwho.is/",
                                         headers={"User-Agent": "Zeta-Monitor"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                d = json.loads(resp.read().decode("utf-8"))
            if not d.get("success", True):
                return None
            conn = d.get("connection", {}) or {}
            return {"ip": d.get("ip", NA), "city": d.get("city", NA),
                    "region": d.get("region", NA), "country": d.get("country", NA),
                    "lat": d.get("latitude"), "lon": d.get("longitude"),
                    "isp": conn.get("isp", conn.get("org", NA)),
                    "asn": conn.get("asn", NA)}
        except Exception:  # noqa: BLE001
            return None

    def connections(self):
        rows = []
        if not psutil:
            return rows
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, PermissionError):
            return None    # permission denied: the UI shows PERMISSION REQUIRED
        except Exception:  # noqa: BLE001
            return rows
        for c in conns:
            proto = "TCP" if c.type == socket.SOCK_STREAM else "UDP"
            la = "%s:%s" % c.laddr if c.laddr else NA
            ra = "%s:%s" % c.raddr if c.raddr else "—"
            name = NA
            if c.pid:
                try:
                    name = psutil.Process(c.pid).name()
                except Exception:  # noqa: BLE001
                    name = NA
            rows.append({"proto": proto, "local": la, "remote": ra,
                         "state": c.status or "—", "pid": c.pid or NA, "process": name})
        return rows

    # ---------------- processes ----------------
    def processes(self, limit=200):
        rows = []
        if not psutil:
            return rows
        if not self._proc_primed:
            for p in psutil.process_iter():
                try:
                    p.cpu_percent(None)
                except Exception:  # noqa: BLE001
                    pass
            self._proc_primed = True
            return rows
        ncpu = psutil.cpu_count() or 1
        for p in psutil.process_iter(["pid", "name", "username", "memory_percent",
                                      "memory_info", "status", "create_time"]):
            try:
                info = p.info
                cpu = p.cpu_percent(None) / ncpu
                rows.append({
                    "pid": info["pid"], "name": info["name"] or NA,
                    "user": info["username"] or NA, "cpu": cpu,
                    "mem_pct": info["memory_percent"] or 0.0,
                    "rss": info["memory_info"].rss if info["memory_info"] else 0,
                    "status": info["status"] or NA,
                    "start": time.strftime("%H:%M:%S", time.localtime(info["create_time"]))
                    if info["create_time"] else NA})
            except Exception:  # noqa: BLE001
                continue
        rows.sort(key=lambda r: r["cpu"], reverse=True)
        return rows[:limit]

    def process_detail(self, pid):
        if not psutil:
            return None
        try:
            p = psutil.Process(pid)
            d = {"pid": pid, "name": p.name(), "exe": NA, "ppid": p.ppid(),
                 "user": NA, "cmdline": NA, "status": p.status(),
                 "children": [], "open_files": NA, "connections": NA}
            try:
                d["exe"] = p.exe()
            except Exception:  # noqa: BLE001
                pass
            try:
                d["user"] = p.username()
            except Exception:  # noqa: BLE001
                pass
            try:
                d["cmdline"] = " ".join(p.cmdline()) or d["name"]
            except Exception:  # noqa: BLE001
                pass
            try:
                d["children"] = [(c.pid, c.name()) for c in p.children()]
                d["tree"] = len(p.children(recursive=True))
            except Exception:  # noqa: BLE001
                d["tree"] = 0
            try:
                io = p.io_counters()
                d["io"] = (io.read_bytes, io.write_bytes)
            except (psutil.AccessDenied, Exception):  # noqa: BLE001
                d["io"] = None
            try:
                d["open_files"] = len(p.open_files())
            except (psutil.AccessDenied, Exception):  # noqa: BLE001
                d["open_files"] = tr("permission required")
            try:
                d["connections"] = len(p.net_connections())
            except (psutil.AccessDenied, Exception):  # noqa: BLE001
                d["connections"] = tr("permission required")
            return d
        except Exception:  # noqa: BLE001
            return None

    def close_tree(self, pid):
        """The program with all its child processes: first a polite request to
        close, then a forced kill for whatever has not responded within 3 seconds.
        Desktop components are protected (same rule as Force Quit)."""
        import sys
        sys.path.insert(0, "/usr/lib/zeta")
        from system import windows
        if windows.is_protected(pid):
            return False, tr("This is part of the ZETA RAYS desktop and can't be closed from here.")
        return windows.force_quit(pid)

    def restart(self, pid):
        """Close the program (with its child processes) and reopen it as it was.
        Only for the user's own programs, never for system ones."""
        import os
        import subprocess
        try:
            p = psutil.Process(pid)
            if p.uids().real != os.getuid():
                return False, tr("You can only restart your own programs.")
            cmd, cwd = p.cmdline(), p.cwd()
        except psutil.NoSuchProcess:
            return False, tr("The process no longer exists.")
        except (psutil.AccessDenied, Exception):  # noqa: BLE001
            return False, tr("Couldn't read how it was started.")
        if not cmd:
            return False, tr("Kernel process: it can't be restarted.")
        ok, msg = self.close_tree(pid)
        if not ok:
            return False, msg
        try:
            subprocess.Popen(cmd, cwd=cwd, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            return False, tr("Closed, but not reopened: {error}").format(error=e)
        return True, tr("{name} restarted.").format(name=os.path.basename(cmd[0]))

    def terminate(self, pid, force=False, wait=3.0):
        """Close a process and report what really happened: (success, message).

        Previously the signal was sent and "closed" was reported right away.
        But "Terminate" is a request: a frozen program (exactly the one you
        want to close) can ignore it, and the Monitor was reporting a falsehood.
        Now we wait up to `wait` seconds and check. Must be called outside
        the UI thread.
        """
        if not psutil:
            return False, tr("Closing processes is not available.")
        name = tr("Process {pid}").format(pid=pid)
        try:
            p = psutil.Process(pid)
            name = p.name()
            p.kill() if force else p.terminate()
        except psutil.NoSuchProcess:
            return True, tr("The process was already closed.")
        except psutil.AccessDenied:
            return False, tr("{name} belongs to the system or to another user: "
                             "for safety, the Monitor won't close it.").format(name=name)
        except Exception as e:  # noqa: BLE001
            return False, tr("Couldn't close the process: {error}").format(error=e)
        _gone, alive = psutil.wait_procs([p], timeout=wait)
        if not alive:
            return True, tr("{name} closed.").format(name=name)
        if not force:
            return False, tr("{name} didn't respond. If it's frozen, use Force Quit.").format(name=name)
        return False, tr("{name} won't close even when forced: it's waiting on the disk "
                         "or the system. Try again shortly.").format(name=name)

    # ---------------- firewall ----------------
    def firewall(self):
        out = {"system": NA, "status": "UNKNOWN", "rules": NA,
               "policies": NA, "text": ""}
        if shutil.which("nft"):
            rs = _run(["nft", "list", "ruleset"])
            if rs.strip():
                out["system"] = "nftables"
                out["status"] = "ACTIVE"
                out["rules"] = len(re.findall(r"\b(drop|accept|reject|jump)\b", rs))
                out["text"] = rs[:8000]
                pol = re.findall(r"policy (\w+)", rs)
                out["policies"] = ", ".join(sorted(set(pol))) or NA
                return out
            out["system"] = "nftables"
            out["status"] = "INACTIVE"
        if shutil.which("ufw"):
            r = _run(["ufw", "status"], c_locale=True)
            if "Status: active" in r:
                out["system"] = "ufw"; out["status"] = "ACTIVE"; out["text"] = r
                return out
        if shutil.which("iptables"):
            r = _run(["iptables", "-S"])
            if r.strip():
                out["system"] = "iptables"
                out["status"] = "ACTIVE" if r.count("\n") > 3 else "INACTIVE"
                out["text"] = r[:8000]
                out["rules"] = r.count("\n")
        return out

    # ---------------- logins / authentication ----------------
    def sessions(self):
        rows = []
        if psutil:
            try:
                for u in psutil.users():
                    rows.append({"user": u.name, "tty": u.terminal or "—",
                                 "host": u.host or tr("local"),
                                 "since": time.strftime("%H:%M", time.localtime(u.started))})
            except Exception:  # noqa: BLE001
                pass
        return rows

    def auth_events(self, limit=40):
        """Authentication events from the system logs (if readable)."""
        events = []
        readable = os.access("/var/log/auth.log", os.R_OK)
        source = None
        if readable:
            source = _run(["tail", "-n", "400", "/var/log/auth.log"])
        else:
            source = _run(["journalctl", "-n", "400", "--no-pager", "-o", "short-iso",
                           "SYSLOG_FACILITY=10"])  # auth
        if not source.strip():
            return {"permission": not readable and not source, "events": events}
        for line in source.splitlines():
            ev = self._parse_auth_line(line)
            if ev:
                events.append(ev)
        return {"permission": False, "events": events[-limit:][::-1]}

    def _parse_auth_line(self, line):
        low = line.lower()
        t = ""
        m = re.search(r"(\d{2}:\d{2}:\d{2})", line)
        if m:
            t = m.group(1)
        ip = ""
        mi = re.search(r"from (\d+\.\d+\.\d+\.\d+)", line)
        if mi:
            ip = mi.group(1)
        user = ""
        mu = re.search(r"for (?:invalid user )?(\w+)", line) or re.search(r"user (\w+)", line)
        if mu:
            user = mu.group(1)
        if "accepted" in low and "sshd" in low:
            return (t, user, ip or "—", "SSH", "LOGIN", "SUCCESS")
        if "failed password" in low or "authentication failure" in low:
            svc = "SSH" if "sshd" in low else "AUTH"
            return (t, user, ip or "—", svc, "LOGIN", "FAILED")
        if "session opened" in low:
            return (t, user, ip or "—", "SESSION", "OPEN", "INFO")
        if "session closed" in low:
            return (t, user, ip or "—", "SESSION", "CLOSE", "INFO")
        if "sudo:" in low and "command=" in low:
            return (t, user, tr("local"), "SUDO", "AUTH", "SUCCESS")
        return None

    # ---------------- services ----------------
    def services(self, limit=120):
        """Every loaded service with an honest state.

        RUNNING       a daemon that is running
        DONE          a one-shot job that completed (active, exited)
        STOPPED       inactive, never needed in this boot
        NOT_APPLICABLE  skipped because its condition is false here (no
                      Bluetooth adapter, not a live session, ...): not an error
        WARNING       a periodic job (started by a timer) that failed: the
                      system keeps working, the job will run again
        FAILED        a service that failed and is not a periodic job
        """
        out = _run(["systemctl", "show", "--all", "--type=service", "--no-pager",
                    "-p", "Id,ActiveState,SubState,ConditionResult,ConditionTimestampMonotonic,TriggeredBy",
                    "*"])
        rows = []
        for block in out.split("\n\n"):
            props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            unit = props.get("Id", "")
            if not unit.endswith(".service"):
                continue
            rows.append({"name": unit[:-8], "state": classify_service(props),
                         "sub": props.get("SubState", "")})
        order = {"FAILED": 0, "WARNING": 1, "RUNNING": 2, "DONE": 3, "STOPPED": 4, "NOT_APPLICABLE": 5}
        rows.sort(key=lambda r: (order.get(r["state"], 9), r["name"]))
        return rows[:limit]

    def service_action(self, name, action):
        if action not in ("start", "stop", "restart"):
            return False, tr("invalid action")
        p = subprocess.run(["pkexec", "systemctl", action, name + ".service"],
                           capture_output=True, text=True)
        return p.returncode == 0, (p.stderr or "").strip()

    # ---------------- security events ----------------
    def security_events(self):
        """Combine the events that are really available (nothing made up)."""
        events = []
        auth = self.auth_events(limit=12)
        for t, user, ip, svc, ev, status in auth.get("events", []):
            sev = "ALERT" if status == "FAILED" else ("NOTICE" if svc == "SUDO" else "INFO")
            events.append((t, "%s %s %s" % (svc, ev, status),
                           tr("{user} from {ip}").format(user=user, ip=ip) if ip and ip != "—" else user, sev))
        for v in failed_verdicts():
            if v["level"] in ("error", "warning"):
                events.append((time.strftime("%H:%M:%S"), v["title"], v["unit"],
                               "ALERT" if v["level"] == "error" else "WARNING"))
        return events


# ---------------- privileged data (read-only helper) ----------------
HELPER = "/usr/libexec/zeta-monitor-helper"


def helper(action, timeout=12):
    """Run one of the helper's read-only actions without a password (sudo -n)."""
    return _run(["sudo", "-n", HELPER, action], timeout=timeout)


def firewall_info():
    """{active, enabled, known, policy_in, policy_out, rules, chains:[...], text}."""
    info = {"known": False, "active": False, "enabled": False, "policy_in": NA,
            "policy_out": NA, "rules": 0, "chains": [], "text": ""}
    raw = helper("firewall")
    if not raw.strip():
        info["active"] = _run(["systemctl", "is-active", "nftables"]).strip() == "active"
        return info
    try:
        d = json.loads(raw)
    except ValueError:
        return info
    info.update(known=True, active=d.get("active"), enabled=d.get("enabled"), text=d.get("text", ""))
    for item in (d.get("ruleset") or {}).get("nftables", []):
        if "chain" in item:
            c = item["chain"]
            info["chains"].append({"table": c.get("table"), "name": c.get("name"),
                                   "hook": c.get("hook", ""), "policy": c.get("policy", "")})
            if c.get("hook") == "input":
                info["policy_in"] = c.get("policy", NA)
            if c.get("hook") == "output":
                info["policy_out"] = c.get("policy", NA)
        elif "rule" in item:
            info["rules"] += 1
    return info


SS_RE = re.compile(r"^(\S+)\s+(\S+)\s+\d+\s+\d+\s+(\S+)\s+(\S+)(?:\s+(.*))?$")


def _split_addr(a):
    if a.startswith("["):
        host, _, port = a[1:].rpartition("]:")
    else:
        host, _, port = a.rpartition(":")
    return host.split("%")[0], port


def sockets_all():
    """All connections (with their process) from the helper; None if unavailable."""
    raw = helper("sockets")
    if not raw.strip():
        return None
    rows = []
    for line in raw.splitlines():
        m = SS_RE.match(line.strip())
        if not m:
            continue
        proto, state, local, peer, procs = m.groups()
        lh, lp = _split_addr(local)
        ph, pp = _split_addr(peer)
        pm = re.search(r'\("([^"]+)",pid=(\d+)', procs or "")
        rows.append({"proto": proto.upper(), "state": state, "lhost": lh, "lport": lp,
                     "rhost": ph, "rport": pp, "process": pm.group(1) if pm else "—",
                     "pid": int(pm.group(2)) if pm else None})
    return rows


STATE_IT = {"ESTAB": tr("Established"), "LISTEN": tr("Listening"), "UNCONN": tr("Listening (UDP)"),
            "TIME-WAIT": tr("Closing"), "CLOSE-WAIT": tr("Closing"), "SYN-SENT": tr("Opening"),
            "SYN-RECV": tr("Opening"), "FIN-WAIT-1": tr("Closing"), "FIN-WAIT-2": tr("Closing"),
            "LAST-ACK": tr("Closing"), "CLOSING": tr("Closing")}


def logind_sessions():
    """Real sessions from logind (Wayland too, which does not write utmp)."""
    rows = []
    out = _run(["loginctl", "list-sessions", "--no-legend"])
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        sid = parts[0]
        props = {}
        for l in _run(["loginctl", "show-session", sid, "-p", "Name", "-p", "Remote", "-p", "RemoteHost",
                       "-p", "Type", "-p", "Class", "-p", "TTY", "-p", "Timestamp", "-p", "State",
                       "-p", "Service"]).splitlines():
            k, _, v = l.partition("=")
            props[k] = v
        if props.get("Class") not in ("user",):
            continue
        kind = {"wayland": trc("session type", "Desktop"), "x11": tr("Desktop (X11)"),
                "tty": tr("Terminal")}.get(props.get("Type"), "")
        remote = props.get("Remote") == "yes" or props.get("Service") == "sshd"
        if remote:
            kind = tr("Remote (SSH)")
        rows.append({"id": sid, "user": props.get("Name", ""), "kind": kind or props.get("Type", ""),
                     "where": props.get("RemoteHost") or props.get("TTY") or tr("local"),
                     "since": props.get("Timestamp", ""), "remote": remote,
                     "active": props.get("State") == "active",
                     "state": {"active": tr("in foreground"), "online": tr("in background"),
                               "closing": tr("closing")}.get(props.get("State"), props.get("State", ""))})
    return rows


def accounts():
    """Human accounts (uid 1000-59999) and root, with role and last login."""
    import grp
    import pwd
    try:
        admins = set(grp.getgrnam("sudo").gr_mem)
    except KeyError:
        admins = set()
    rows = []
    for u in pwd.getpwall():
        if not (u.pw_uid == 0 or 1000 <= u.pw_uid < 60000):
            continue
        locked = False
        admin = u.pw_uid != 0 and u.pw_name in admins
        rows.append({"user": u.pw_name, "name": u.pw_gecos.split(",")[0], "uid": u.pw_uid,
                     "admin": admin,
                     "role": tr("System") if u.pw_uid == 0 else (tr("Administrator") if admin else tr("Standard")),
                     "shell": os.path.basename(u.pw_shell), "home": u.pw_dir,
                     "login": u.pw_shell not in ("/usr/sbin/nologin", "/bin/false"), "locked": locked})
    last = {}
    for h in login_history(200):
        last.setdefault(h["user"], h["text"])
    for r in rows:
        r["last"] = last.get(r["user"], "—")
    return rows


def login_history(limit=25):
    """Recent logins from the wtmpdb database (read-only).

    The logout time is written by PAM when the session closes properly.
    If the computer shuts off abruptly (power loss, freeze, forced reboot)
    that time is never written. A session that started before the current
    boot, however, is certainly no longer open: calling it "still logged in"
    would be false. It is marked for what it is: interrupted.
    """
    import sqlite3
    rows = []
    boot_us = 0
    if psutil:
        try:
            boot_us = psutil.boot_time() * 1e6
        except (OSError, RuntimeError):
            boot_us = 0
    try:
        db = sqlite3.connect("file:/var/lib/wtmpdb/wtmp.db?mode=ro", uri=True, timeout=2)
        cur = db.execute("SELECT User, TTY, RemoteHost, Service, Login, Logout FROM wtmp "
                         "WHERE Type = 3 AND User != 'sddm' ORDER BY Login DESC LIMIT ?", (limit,))
        for user, tty, host, svc, login, logout in cur:
            when = short_datetime((login or 0) / 1e6)
            # state: stable key for other programs ("closed", "interrupted", "open")
            if logout:
                dur = int(((logout or 0) - (login or 0)) / 6e7)
                state = "closed"
                end = tr("until {time} ({minutes} min)").format(
                    time=time.strftime("%H:%M", time.localtime(logout / 1e6)), minutes=dur)
            elif boot_us and (login or 0) < boot_us:
                state = "interrupted"
                end = tr("interrupted (sudden shutdown)")
            else:
                state = "open"
                end = tr("still logged in")
            src = host or {"sddm": tr("desktop"), "sshd": "SSH",
                           "login": tr("console")}.get(svc or "", svc or "")
            rows.append({"user": user or "—", "tty": tty or "—", "state": state,
                         "text": "%s · %s · %s" % (when, src, end)})
        db.close()
    except sqlite3.Error as e:
        print("monitor: login history not readable: %s" % e, file=sys.stderr)
    except OSError as e:
        print("monitor: login history not reachable: %s" % e, file=sys.stderr)
    return rows


def vpn_tunnels():
    """Active tunnel interfaces (WireGuard, OpenVPN, etc.)."""
    if not psutil:
        return []
    out = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        if name.startswith(("wg", "tun", "tap", "ppp", "ipsec", "nordlynx", "proton")):
            ip = next((a.address for a in addrs if a.family == socket.AF_INET), NA)
            st = stats.get(name)
            out.append({"name": name, "ip": ip, "up": bool(st and st.isup)})
    return out


# ---- ping (blocking: run it in a thread) ----
def ping(host, timeout=1.0):
    out = _run(["ping", "-c", "1", "-W", str(int(max(1, timeout))), host], timeout=timeout + 1.5,
               c_locale=True)
    if not out:
        return None
    m = re.search(r"time=([\d.]+) ms", out)
    return float(m.group(1)) if m else None
