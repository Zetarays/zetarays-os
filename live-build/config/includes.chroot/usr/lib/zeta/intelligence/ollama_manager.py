# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Ollama management (the local AI model).

Everything goes through Ollama's local API (http://127.0.0.1:11434): no
terminal commands, no special permissions, except starting and stopping the
service, which ask for the password (pkexec). Every function has a timeout:
if Ollama does not respond, the interface says so instead of hanging.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

from i18n import tr

BASE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if not BASE.startswith("http"):
    BASE = "http://" + BASE


def _get(path: str, timeout: float = 3.0):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _request(method: str, path: str, data: dict, timeout: float = 30.0):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"}, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def installed() -> bool:
    return bool(shutil.which("ollama"))


def service_active() -> bool:
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", "ollama"],
                              timeout=3).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def version() -> str:
    try:
        return _get("/api/version").get("version", "")
    except (OSError, ValueError):
        return ""


def models() -> list[dict]:
    """Installed models: name, size (GB), family, parameters."""
    try:
        data = _get("/api/tags").get("models", [])
    except (OSError, ValueError):
        return []
    out = []
    for m in data:
        d = m.get("details") or {}
        out.append({"name": m.get("name", ""), "gb": (m.get("size") or 0) / 1e9,
                    "family": d.get("family", ""), "parameters": d.get("parameter_size", ""),
                    "quantization": d.get("quantization_level", "")})
    return sorted(out, key=lambda m: m["name"])


def loaded_models() -> list[dict]:
    """Models currently in memory: name, RAM/VRAM used (GB), expiry."""
    try:
        data = _get("/api/ps").get("models", [])
    except (OSError, ValueError):
        return []
    return [{"name": m.get("name", ""), "gb": (m.get("size") or 0) / 1e9,
             "vram_gb": (m.get("size_vram") or 0) / 1e9, "expires": m.get("expires_at", "")}
            for m in data]


def process_resources() -> dict:
    """Memory and CPU of the Ollama processes (server and model runner)."""
    tot_rss, cpu = 0, 0.0
    try:
        import psutil
        for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
            n = (p.info.get("name") or "").lower()
            if n.startswith("ollama") or n in ("llama-server", "ollama_llama_server"):
                tot_rss += getattr(p.info.get("memory_info"), "rss", 0) or 0
                cpu += p.info.get("cpu_percent") or 0.0
    except Exception:  # noqa: BLE001 - nice-to-have figure: if missing, zero
        pass
    return {"ram_gb": tot_rss / 1e9, "cpu": cpu}


def free_memory() -> int:
    """Unload the loaded models from memory (they stay installed)."""
    n = 0
    for m in loaded_models():
        try:
            _request("POST", "/api/generate", {"model": m["name"], "keep_alive": 0}, 20).read()
            n += 1
        except (OSError, ValueError):
            pass
    return n


def remove(name: str) -> tuple[bool, str]:
    try:
        _request("DELETE", "/api/delete", {"model": name}, 60).read()
        return True, tr("Model {name} removed.").format(name=name)
    except urllib.error.HTTPError as e:
        return False, tr("Ollama refused: {reason}").format(
            reason=e.read().decode("utf-8", "replace")[:200])
    except OSError as e:
        return False, tr("Ollama isn't responding ({error}).").format(error=e)


def download(name: str, progress=None, should_stop=None) -> tuple[bool, str]:
    """Download a model from the Ollama library (ollama.com/library).

    progress(text, fraction 0..1 or None) is called as it progresses;
    should_stop() -> True stops the download (the rest is resumed next time:
    Ollama keeps the parts already downloaded).
    """
    name = name.strip()
    if not name or any(c.isspace() for c in name):
        return False, tr("Invalid model name (example: qwen3:1.7b).")
    try:
        resp = _request("POST", "/api/pull", {"model": name, "stream": True}, 3600)
    except urllib.error.HTTPError as e:
        return False, tr("Ollama refused: {reason}").format(
            reason=e.read().decode("utf-8", "replace")[:200])
    except OSError as e:
        return False, tr("Ollama isn't responding ({error}).").format(error=e)
    try:
        for line in resp:
            if should_stop and should_stop():
                resp.close()
                return False, tr("Download stopped: resuming it picks up where it left off.")
            try:
                d = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if d.get("error"):
                return False, tr("Error: {error}").format(error=d["error"])
            tot, done = d.get("total"), d.get("completed")
            fraction = (done / tot) if tot and done is not None else None
            if progress:
                text = d.get("status", "")
                if fraction is not None:
                    text = tr("{status}  {percent} of {size} GB").format(
                        status=text, percent="%.0f%%" % (fraction * 100), size="%.1f" % (tot / 1e9))
                progress(text, fraction)
            if d.get("status") == "success":
                return True, tr("Model {name} downloaded.").format(name=name)
    except OSError as e:
        return False, tr("Download interrupted ({error}).").format(error=e)
    finally:
        resp.close()
    return False, tr("Download not completed.")


def service(operation: str) -> tuple[bool, str]:
    """Start, stop or restart the service (asks for the password: pkexec)."""
    if operation not in ("start", "stop", "restart"):
        return False, tr("Unknown action.")
    try:
        p = subprocess.run(["pkexec", "systemctl", operation, "ollama"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if p.returncode == 0:
        return True, {"start": tr("Ollama started."), "stop": tr("Ollama stopped."),
                      "restart": tr("Ollama restarted.")}[operation]
    if p.returncode in (126, 127):
        return False, tr("Operation canceled.")
    return False, (p.stderr or tr("Error")).strip()[:200]
