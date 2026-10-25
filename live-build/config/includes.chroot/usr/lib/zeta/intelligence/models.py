# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — which local model, on which computer.

ZETA RAYS answers only with models that run on this computer (Ollama, which
uses llama.cpp and listens on 127.0.0.1). One model does not fit every
machine: an 8 GB computer needs room for the desktop and the voice, an Intel
N-series mini PC (N100, N150, N200, N97) has four slow cores and one memory
channel, a 16 GB computer can afford a bigger model. This module looks at
the machine once and decides:

  profile     RAM / CPU                      preferred models (first installed wins)
  low-power   Intel N-series, any RAM        PROFILES["low-power"]
  8gb         below 12 GB                    PROFILES["8gb"]
  16gb        12 GB and more                 PROFILES["16gb"]
  large       24 GB and 8+ threads           PROFILES["large"]

The choice in Settings › AI (a model the user picked) always wins. When the
chosen model cannot be loaded (not enough free memory, file damaged), a
smaller installed model answers that question instead, and ZETA says so: the
fallback is always another local model, never an online service.

The model lists and the reasons for them are in docs/AI.md ("Choosing the
model"), with the measurements they come from.
"""
from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass

from . import resources

# Ollama names. Every profile lists its models best first; a model that is
# not installed is skipped. The image ships DEFAULT_MODEL and SMALL_MODEL;
# HIGH_MODEL is only recommended (download on click) to big computers.
# Measured on the same prompts, options and 4-core container (docs/AI.md):
#   qwen3:4b-instruct  3.2 GB loaded, 12.5 words/s, the best Italian
#   granite4:micro-h   2.4 GB loaded, 17.7 words/s, good Italian, hybrid
#                      Mamba-2 (lighter to read and to run on a slow CPU)
#   granite4.1:8b      5.7 GB loaded, 7.8 words/s, the most fluent Italian of
#                      the larger models, 10/10 commands (download on click)
DEFAULT_MODEL = "qwen3:4b-instruct"
SMALL_MODEL = "granite4:micro-h"
HIGH_MODEL = "granite4.1:8b"

PROFILES = {
    # Intel N-series: speed matters most (4 slow cores, one memory channel);
    # short context, the faster and lighter model first
    "low-power": {"models": [SMALL_MODEL, DEFAULT_MODEL], "context": 2048},
    # 8 GB: room for the desktop, the browser and the voice first
    "8gb": {"models": [SMALL_MODEL, DEFAULT_MODEL], "context": 4096},
    # 12 GB and more: the best Italian and English
    "16gb": {"models": [DEFAULT_MODEL, SMALL_MODEL], "context": 4096},
    # 24 GB and 8 processor threads or more: a larger model is worth it
    "large": {"models": [HIGH_MODEL, DEFAULT_MODEL, SMALL_MODEL], "context": 8192},
}

# Models that think aloud unless asked not to: ZETA always asks them not to
# (a reasoning trace costs seconds before the first useful word).
THINKING_FAMILIES = ("qwen3.5:", "qwen3:", "gemma4:", "deepseek-r1", "lfm2.5")

# Intel low-power processors: "Intel(R) N100", "N150", "N200", "N97", "N95"
_LOW_POWER_CPU = re.compile(r"\bIntel\b.*\b(?:N\d{2,3}|N\d{3}E?)\b", re.I)

CPUINFO = "/proc/cpuinfo"


@dataclass(frozen=True)
class Machine:
    ram_gb: float           # nominal RAM (resources.nominal_memory_gb)
    cpu: str                # model name, "" if unknown
    cores: int              # logical processors
    profile: str            # a key of PROFILES


def _cpu_name() -> str:
    try:
        with open(CPUINFO, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def profile_for(ram_gb: float, cpu: str, cores: int = 0) -> str:
    if _LOW_POWER_CPU.search(cpu or ""):
        return "low-power"
    if 0 < ram_gb < 12:
        return "8gb"
    if ram_gb >= 24 and cores >= 8:
        return "large"
    return "16gb"


@functools.lru_cache(maxsize=1)
def machine() -> Machine:
    ram = resources.nominal_memory_gb()
    cpu = _cpu_name()
    cores = os.cpu_count() or 1
    return Machine(ram_gb=ram, cpu=cpu, cores=cores, profile=profile_for(ram, cpu, cores))


def preferred(profile: str | None = None) -> list[str]:
    return list(PROFILES[profile or machine().profile]["models"])


def context_size(profile: str | None = None) -> int:
    return int(PROFILES[profile or machine().profile]["context"])


def thinks(model: str) -> bool:
    """A model family that reasons before answering unless told not to."""
    return any(model.startswith(f) for f in THINKING_FAMILIES) and "instruct" not in model


def _base_name(name: str) -> str:
    """"qwen3:4b-instruct" and "qwen3:4b-instruct-2507-q4_K_M" are the same model."""
    return name.split("@")[0]


def choose(installed: dict, profile: str | None = None) -> str:
    """The model to use when the user has not picked one.

    `installed`: {name: file size in GB} as Ollama lists them. The first
    preferred model that is installed; else the smallest installed model
    whose loaded size fits the machine; else the profile's first choice
    (Ollama then says it is missing, and Settings offers to download it).
    """
    installed = {n: gb for n, gb in installed.items() if not is_cloud(n)}
    names = list(installed)
    for want in preferred(profile):
        for have in names:
            if _base_name(have) == want or have.startswith(want + "-"):
                return have
    room = resources.nominal_memory_gb() - resources.MARGIN_GB - 2.0   # the desktop's share
    fitting = sorted((gb, n) for n, gb in installed.items()
                     if gb > 0 and resources.model_memory_gb(gb) <= max(room, 1.0)
                     and not is_embedding(n))
    if fitting:
        return fitting[-1][1]                  # the largest that fits
    chat = [n for n in names if not is_embedding(n)]
    return chat[0] if chat else preferred(profile)[0]


def fallback(current: str, installed: dict) -> str:
    """A smaller installed model that fits in the free memory now, or ""."""
    size = installed.get(current, 0.0)
    smaller = sorted((gb, n) for n, gb in installed.items()
                     if n != current and 0 < gb < (size or 99) and not is_embedding(n)
                     and not is_cloud(n)
                     and resources.memory_for_model(resources.model_memory_gb(gb)))
    return smaller[-1][1] if smaller else ""


def reason(profile: str) -> str:
    """Why the profile's first model suits this computer (Settings › AI)."""
    from i18n import tr
    return {
        "low-power": tr("faster on low-power processors and lighter on memory, with good "
                        "answers in Italian and English"),
        "8gb": tr("good answers in Italian and English with room left for the desktop and the voice"),
        "16gb": tr("the best answers in Italian and English among the models tested"),
        "large": tr("a larger model for computers with plenty of memory and processor: better "
                    "answers, a little slower"),
    }.get(profile, "")


def is_cloud(name: str) -> bool:
    """An Ollama "cloud" model ("gpt-oss:120b-cloud", "x:cloud"): it would run
    on ollama.com, not here. ZETA never uses one (and the service has its
    cloud features off: OLLAMA_NO_CLOUD=1)."""
    tag = name.split(":", 1)[1] if ":" in name else ""
    return tag == "cloud" or tag.endswith("-cloud") or name.endswith("-cloud")


def is_embedding(name: str) -> bool:
    return any(k in name for k in ("embed", "bge-", "minilm", "nomic-embed"))
