# SPDX-License-Identifier: GPL-3.0-or-later
"""Machine resources: how much memory there really is.

The default local AI model (qwen3:4b-instruct since 2.1, a 2.5 GB file) takes
about 3.7 GB once loaded (measured with num_ctx 4096 and the q8_0 KV cache of
the ZETA RAYS Ollama service). Keeping it in memory makes replies instant,
but on a computer with little RAM that is exactly what makes everything else
crawl: the desktop starts swapping to disk and the user sees freezes and
slowdowns. This module decides, once and in one place only, how much we can
afford. The goal: the whole system runs well on 8 GB.

  RAM      at login    after a reply   before loading
  < 6 GB   never       2 minutes       check free memory; suggest a smaller
                                       model or an online service
  6-11 GB  never       5 minutes       check free memory (8 GB machines)
  12-15    never       10 minutes      check free memory
  16+ GB   yes         30 minutes      check free memory

"Check free memory" = MemAvailable must hold the model plus a margin for the
rest of the system; otherwise ZETA says so (and suggests qwen3:1.7b or an
online service) instead of loading it and pushing the computer into swap.
The Ollama service keeps at most one model loaded (OLLAMA_MAX_LOADED_MODELS=1,
set by the build hook).
"""
from __future__ import annotations

import math

from i18n import tr

# Read by the functions below; the tests point it to synthetic files.
MEMINFO = "/proc/meminfo"

# Thresholds in GB of nominal memory (see nominal_memory_gb).
# Loading the model at login kept gigabytes busy on every boot even if ZETA
# was never opened: we only do it where memory is truly plentiful. Elsewhere
# it loads when ZETA is opened or asked (zeta-core starts it while the user
# types) and is released after keep_alive().
PRELOAD_THRESHOLD = 16.0    # below: the model is not loaded at login
COMFORTABLE_THRESHOLD = 16.0  # from here: kept warm for half an hour
ROOMY_THRESHOLD = 12.0      # from here: ten minutes
# Below this much RAM a model like the default one (3.7 GB loaded) leaves too
# little for the desktop: it is unloaded almost right after use, and Settings
# suggests a smaller model or an online service.
LOW_RAM_THRESHOLD = 6.0
SHORT_NOW_GB = 0.6          # free memory below this: unload soon, on any machine

# A smaller model that still answers well (the download field in Settings › AI)
SMALLER_MODEL = "qwen3:1.7b"


def _meminfo(field: str) -> float:
    """A /proc/meminfo field in GB (0.0 if unreadable)."""
    try:
        with open(MEMINFO) as f:
            for line in f:
                if line.startswith(field + ":"):
                    return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def total_memory_gb() -> float:
    """Total memory as seen by the kernel, in GB (0.0 if unreadable)."""
    return _meminfo("MemTotal")


def nominal_memory_gb() -> float:
    """The machine's nominal RAM: the value compared against the thresholds.

    The kernel never sees all of the installed memory: part of it goes to the
    firmware, the integrated graphics and the kernel's own structures. An 8 GB
    computer (or virtual machine) reports about 7.7 GB, a 4 GB one about 3.8.
    Comparing that value with "8 GB", the thresholds never matched on 8 GB
    machines. Rounding up to the next integer recovers the real size.
    """
    gb = total_memory_gb()
    if gb <= 0:
        return 0.0
    return float(math.ceil(gb - 0.05))


def available_memory_gb() -> float:
    """Memory actually available now, not counting reclaimable cache."""
    return _meminfo("MemAvailable")


def keep_alive() -> str:
    """How long to keep the model in memory after the last question.

    On a roomy machine it pays to keep it warm for a long time: reloading it
    costs seconds. On a small machine the opposite holds: 3.7 GB held for half
    an hour is worth less than a desktop that stays smooth.
    """
    gb = nominal_memory_gb()
    if gb <= 0:
        return "5m"
    # Memory short right now (other apps grew while the model was loaded):
    # release it soon after this reply, whatever the size of the machine.
    free = available_memory_gb()
    if 0 < free < SHORT_NOW_GB:
        return "1m"
    if gb < LOW_RAM_THRESHOLD:
        return "2m"
    if gb < ROOMY_THRESHOLD:
        return "5m"
    if gb < COMFORTABLE_THRESHOLD:
        return "10m"
    return "30m"


def preload_allowed() -> bool:
    """Whether it is worth loading the model into memory right at login."""
    return nominal_memory_gb() >= PRELOAD_THRESHOLD


# How much the default local model takes once loaded, plus the margin the rest
# of the system must be able to keep. Below this threshold loading it doesn't
# just slow things down: it sends the computer into swap and freezes it.
# Measured with Ollama 0.40 (num_ctx 4096, q8_0 KV cache): qwen3:4b-instruct,
# a 2.5 GB file, takes about 3.7 GB loaded, about 1.45 times the file size.
MODEL_GB = 3.7
MARGIN_GB = 0.7
LOADED_PER_FILE_GB = 1.45


def model_memory_gb(file_gb: float = 0.0) -> float:
    """Memory a model needs once loaded, from the size of its file (the
    default model's figure when the size is unknown)."""
    return file_gb * LOADED_PER_FILE_GB if file_gb > 0 else MODEL_GB


def low_ram_advice(model_gb: float = 0.0) -> str:
    """A suggestion for computers with little RAM, or "" when there is room."""
    gb = nominal_memory_gb()
    if gb <= 0 or gb >= LOW_RAM_THRESHOLD or (model_gb or MODEL_GB) < 2.5:
        return ""
    return tr("This computer has {gb} GB of RAM: the local model would leave little for "
              "everything else. Choose a smaller model (for example {model}) or an "
              "online service in Settings › AI.").format(gb="%.0f" % gb, model=SMALLER_MODEL)


def memory_for_model(model_gb: float = 0.0) -> bool:
    """True if there is room to load the model without freezing the computer.

    MemAvailable must hold the model and still leave a margin: below that,
    loading means swapping (or, on the live system without swap, the hang
    the user perceives as "it froze"). Better to tell them.
    """
    available = available_memory_gb()
    if available <= 0:
        return True          # can't measure it: don't forbid anything
    return available >= (model_gb or MODEL_GB) + MARGIN_GB


def memory_reason(model_gb: float = 0.0) -> str:
    """Explanation shown to the user when there isn't enough memory."""
    text = tr("There isn't enough free memory for the local model "
              "(it needs about {needed} GB, {free} GB free). Close some "
              "apps and try again.").format(needed="%.1f" % ((model_gb or MODEL_GB) + MARGIN_GB),
                                            free="%.1f" % available_memory_gb())
    advice = low_ram_advice(model_gb)
    if not advice and (model_gb or MODEL_GB) >= 2.5:
        advice = tr("Or choose a smaller model (for example {model}, download it in Settings › AI) "
                    "or an online service.").format(model=SMALLER_MODEL)
    return text + (" " + advice if advice else "")


def plan(model_gb: float = 0.0) -> dict:
    """The whole decision for this machine, now (Settings and the tests)."""
    need = model_gb or MODEL_GB
    return {"nominal_gb": nominal_memory_gb(), "available_gb": available_memory_gb(),
            "preload_at_login": preload_allowed(), "keep_alive": keep_alive(),
            "can_load": memory_for_model(need), "advice": low_ram_advice(need)}
