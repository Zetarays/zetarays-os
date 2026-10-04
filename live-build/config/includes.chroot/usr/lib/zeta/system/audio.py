# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — audio (PipeWire/WirePlumber).

Elenchi strutturati da `pw-dump` (JSON), volumi e dispositivo predefinito
con `wpctl`. Volumi espressi da 0.0 a 1.0 (fino a 1.5 per l'amplificazione).
"""
import json
import re

from . import run

SINK, SOURCE = "Audio/Sink", "Audio/Source"
DEFAULT_SINK, DEFAULT_SOURCE = "@DEFAULT_AUDIO_SINK@", "@DEFAULT_AUDIO_SOURCE@"


def _dump():
    out = run(["pw-dump"], timeout=4)
    try:
        return json.loads(out) if out else []
    except ValueError:
        return []


def _defaults(objs):
    names = {}
    for o in objs:
        if o.get("type") != "PipeWire:Interface:Metadata":
            continue
        for m in (o.get("metadata") or []):
            if m.get("key") in ("default.audio.sink", "default.audio.source"):
                val = m.get("value")
                if isinstance(val, dict):
                    names[m["key"]] = val.get("name")
                elif isinstance(val, str):
                    try:
                        names[m["key"]] = json.loads(val).get("name")
                    except ValueError:
                        pass
    return names


def devices(kind=SINK):
    """Uscite (kind=SINK) o ingressi (kind=SOURCE): [{id, name, label, default}]."""
    objs = _dump()
    defaults = _defaults(objs)
    key = "default.audio.sink" if kind == SINK else "default.audio.source"
    rows = []
    for o in objs:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        props = (o.get("info") or {}).get("props") or {}
        if props.get("media.class") != kind:
            continue
        name = props.get("node.name", "")
        label = props.get("node.description") or props.get("node.nick") or name
        rows.append({"id": o.get("id"), "name": name, "label": _nice(label),
                     "default": name == defaults.get(key)})
    if rows and not any(r["default"] for r in rows):
        rows[0]["default"] = True
    return rows


def streams():
    """App che stanno riproducendo audio: [{id, app, label}]."""
    rows = []
    for o in _dump():
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        props = (o.get("info") or {}).get("props") or {}
        if props.get("media.class") != "Stream/Output/Audio":
            continue
        app = props.get("application.name") or props.get("node.name") or "App"
        rows.append({"id": o.get("id"), "app": app,
                     "label": props.get("media.name") or ""})
    return rows


def _nice(label):
    # "Built-in Audio Analog Stereo" -> "Audio integrato (analogico stereo)"
    t = label.replace("Built-in Audio", "Audio integrato")
    t = re.sub(r"\bAnalog Stereo\b", "analogico stereo", t)
    t = re.sub(r"\bDigital Stereo\b", "digitale stereo", t)
    t = re.sub(r"\bHDMI\b", "HDMI", t)
    return t


def volume(target=DEFAULT_SINK):
    """(volume 0..1.5, muto) oppure (None, False) se non c'è audio."""
    out = run(["wpctl", "get-volume", str(target)], timeout=3)
    m = re.search(r"Volume:\s*([\d.]+)", out or "")
    if not m:
        return None, False
    return float(m.group(1)), "MUTED" in out


def set_volume(value, target=DEFAULT_SINK):
    value = max(0.0, min(1.5, value))
    run(["wpctl", "set-volume", "-l", "1.5", str(target), "%.2f" % value], timeout=3)


def set_mute(muted, target=DEFAULT_SINK):
    run(["wpctl", "set-mute", str(target), "1" if muted else "0"], timeout=3)


def set_default(node_id):
    run(["wpctl", "set-default", str(node_id)], timeout=3)


def available():
    return volume()[0] is not None
