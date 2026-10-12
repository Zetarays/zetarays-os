# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — audio (PipeWire/WirePlumber).

Structured lists from `pw-dump` (JSON), volumes and default device through
`wpctl`. Volumes range from 0.0 to 1.0 (up to 1.5 for amplification).
"""
import json
import re

from i18n import tr

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
    """Outputs (kind=SINK) or inputs (kind=SOURCE): [{id, name, label, default}]."""
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
    """Apps that are currently playing audio: [{id, app, label}]."""
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
    # "Built-in Audio Analog Stereo" -> translated "Built-in Audio (Analog Stereo)"
    t = label.replace("Built-in Audio", tr("Built-in Audio"))
    t = re.sub(r"\bAnalog Stereo\b", lambda _m: tr("Analog Stereo"), t)
    t = re.sub(r"\bDigital Stereo\b", lambda _m: tr("Digital Stereo"), t)
    t = re.sub(r"\bHDMI\b", "HDMI", t)
    return t


# wpctl prints and parses numbers according to the system locale (in Italian
# «0,40»): always use C, so the volume is read and written with a dot.
_WPCTL = ["env", "LC_ALL=C", "wpctl"]


def volume(target=DEFAULT_SINK):
    """(volume 0..1.5, muted), or (None, False) if there is no audio."""
    out = run(_WPCTL + ["get-volume", str(target)], timeout=3)
    m = re.search(r"Volume:\s*([\d.]+)", out or "")
    if not m:
        return None, False
    return float(m.group(1)), "MUTED" in out


def set_volume(value, target=DEFAULT_SINK):
    value = max(0.0, min(1.5, value))
    run(_WPCTL + ["set-volume", "-l", "1.5", str(target), "%.2f" % value], timeout=3)


def set_mute(muted, target=DEFAULT_SINK):
    run(_WPCTL + ["set-mute", str(target), "1" if muted else "0"], timeout=3)


def set_default(node_id):
    run(_WPCTL + ["set-default", str(node_id)], timeout=3)


def available():
    return volume()[0] is not None
