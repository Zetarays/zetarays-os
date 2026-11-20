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
# Measured on the same prompts, options and 4-core container (docs/AI.md,
# November 2026, Ollama 0.40.16):
#   qwen3:4b-instruct  3.1 GiB loaded, 15.1 tokens/s, the best Italian
#   granite4.2:3b      2.5 GiB loaded, 16.7 tokens/s, good Italian, 10/10
#                      commands; it thinks unless told not to (think: false)
#   granite4.1:8b      5.6 GiB loaded, 6.9 tokens/s, the most fluent Italian of
#                      the larger models, 10/10 commands (download on click)
DEFAULT_MODEL = "qwen3:4b-instruct"
SMALL_MODEL = "granite4.2:3b"
HIGH_MODEL = "granite4.1:8b"
# The small model of 2.5 (9/10 commands). Not in the 3.0 image any more, but
# a computer that has it keeps using it until SMALL_MODEL is downloaded
# (Settings › AI offers the download): it stays in every list, after the
# models that replace it, so ZETA never goes silent after an upgrade.
LEGACY_SMALL_MODEL = "granite4:micro-h"

PROFILES = {
    # Intel N-series: speed matters most (4 slow cores, one memory channel);
    # short context, the faster and lighter model first
    "low-power": {"models": [SMALL_MODEL, LEGACY_SMALL_MODEL, DEFAULT_MODEL], "context": 2048},
    # 8 GB: room for the desktop, the browser and the voice first
    "8gb": {"models": [SMALL_MODEL, LEGACY_SMALL_MODEL, DEFAULT_MODEL], "context": 4096},
    # 12 GB and more: the best Italian and English
    "16gb": {"models": [DEFAULT_MODEL, SMALL_MODEL, LEGACY_SMALL_MODEL], "context": 4096},
    # 24 GB and 8 processor threads or more: a larger model is worth it
    "large": {"models": [HIGH_MODEL, DEFAULT_MODEL, SMALL_MODEL, LEGACY_SMALL_MODEL],
              "context": 8192},
}

# Models that think aloud unless asked not to: ZETA always asks them not to
# (a reasoning trace costs seconds before the first useful word). Granite 4.2
# thinks by default (Granite 4.0 and 4.1 do not).
THINKING_FAMILIES = ("qwen3.5:", "qwen3:", "gemma4:", "deepseek-r1", "lfm2.5", "lfm3",
                     "granite4.2:")

# Memory a model really takes once loaded (GiB reported by `ollama ps`,
# context 4096, q8_0 KV cache, Ollama 0.40.16; docs/AI.md). The estimate
# from the file size (resources.LOADED_PER_FILE_GB) is kept for the others.
LOADED_GB = {
    "qwen3:4b-instruct": 3.15 * 1.074,
    "granite4.2:3b": 2.47 * 1.074,
    "granite4:micro-h": 2.29 * 1.074,
    "granite4.1:8b": 5.64 * 1.074,
}

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


def installed_as(want: str, names) -> str:
    """The installed name of a model ("qwen3:4b-instruct" may be installed as
    "qwen3:4b-instruct-2507-q4_K_M"), or ""."""
    for have in names:
        if _base_name(have) == want or have.startswith(want + "-"):
            return have
    return ""


def loaded_gb(name: str, file_gb: float = 0.0) -> float:
    """Memory the model needs once loaded: measured when known, else
    estimated from its file (resources.model_memory_gb)."""
    for known, gb in LOADED_GB.items():
        if name and installed_as(known, [name]):
            return gb
    return resources.model_memory_gb(file_gb)


def resolve(chosen: str, installed: dict, profile: str | None = None) -> str:
    """The model that will really answer.

    The user's choice (Settings › AI) wins while it is installed. A choice
    that is not installed any more (the 2.5 small model granite4:micro-h is
    not in the 3.0 image: a home folder kept across the upgrade still names
    it) gives way to the best installed model for this computer, instead of
    an error at every question. When the list of installed models is unknown
    (Ollama not running), the choice is kept: there is nothing better to say.
    """
    chosen = "" if is_cloud(chosen or "") else (chosen or "")
    if chosen and (not installed or installed_as(chosen, list(installed)) or chosen in installed):
        return installed_as(chosen, list(installed)) or chosen
    return choose(installed or {}, profile)


def stale_choice(chosen: str, installed: dict) -> bool:
    """The user picked a model that is not installed (any more)."""
    return bool(chosen and installed and not is_cloud(chosen)
                and not installed_as(chosen, list(installed)) and chosen not in installed)


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
        have = installed_as(want, names)
        if have:
            return have
    room = resources.nominal_memory_gb() - resources.MARGIN_GB - 2.0   # the desktop's share
    fitting = sorted((gb, n) for n, gb in installed.items()
                     if gb > 0 and loaded_gb(n, gb) <= max(room, 1.0)
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
                     and resources.memory_for_model(loaded_gb(n, gb)))
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
