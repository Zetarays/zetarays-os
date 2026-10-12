# SPDX-License-Identifier: GPL-3.0-or-later
"""Machine resources: how much memory there really is.

The local AI model takes about 1.8 GB. Keeping it in memory makes replies
instant, but on a computer with little RAM that is exactly what makes
everything else crawl: the desktop starts swapping to disk and the user sees
freezes and slowdowns. This module decides, once and in one place only, how
much we can afford.
"""
from __future__ import annotations

from i18n import tr

# Thresholds in GB of nominal memory (see nominal_memory_gb).
# The model loads from cold in 1-2 s (measured): it is enough to start when
# ZETA is opened (zeta-core does that) while the user types the question.
# Loading it at login kept 1.8 GB busy for 5 minutes on every boot even if
# ZETA was never opened: we only do it where memory is truly plentiful.
PRELOAD_THRESHOLD = 16.0    # below: the model is not loaded at login
COMFORTABLE_THRESHOLD = 8.0        # above: it can be kept warm for a long time
TIGHT_THRESHOLD = 4.0       # below: it is unloaded almost right after use


def total_memory_gb() -> float:
    """Total memory as seen by the kernel, in GB (0.0 if unreadable)."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def nominal_memory_gb() -> float:
    """The machine's nominal RAM: the value compared against the thresholds.

    The kernel never sees all of the installed memory: part of it goes to the
    firmware, the integrated graphics and the kernel's own structures. An 8 GB
    computer (or virtual machine) reports about 7.7 GB, a 4 GB one about 3.8.
    Comparing that value with "8 GB", preloading never kicked in on 8 GB
    machines, i.e. exactly the ones the threshold was designed for.
    Rounding up to the next integer recovers the real size.
    """
    gb = total_memory_gb()
    if gb <= 0:
        return 0.0
    import math
    return float(math.ceil(gb - 0.05))


def available_memory_gb() -> float:
    """Memory actually available now, not counting reclaimable cache."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def keep_alive() -> str:
    """How long to keep the model in memory after the last question.

    On a roomy machine it pays to keep it warm for a long time: reloading it
    costs tens of seconds. On a small machine the opposite holds: 1.8 GB held
    for half an hour is worth less than a desktop that stays smooth.
    """
    gb = nominal_memory_gb()
    if gb <= 0:
        return "5m"
    if gb < TIGHT_THRESHOLD:
        return "2m"
    if gb < COMFORTABLE_THRESHOLD:
        return "10m"
    return "30m"


def preload_allowed() -> bool:
    """Whether it is worth loading the model into memory right at login."""
    return nominal_memory_gb() >= PRELOAD_THRESHOLD


# How much the local model takes once loaded, plus the margin the rest of the
# system must be able to keep. Below this threshold loading it doesn't just
# slow things down: it sends the computer into swap and freezes it.
MODEL_GB = 1.9
MARGIN_GB = 0.7


def memory_for_model() -> bool:
    """True if there is room to load the model without freezing the computer.

    The case that matters is the live system: it runs from the image, memory
    is scarce and there is no swap space on disk. Loading a nearly
    two-gigabyte model there means the hang the user perceives as "it froze".
    Better to tell them.
    """
    available = available_memory_gb()
    if available <= 0:
        return True          # can't measure it: don't forbid anything
    return available >= MODEL_GB + MARGIN_GB


def memory_reason() -> str:
    """Explanation shown to the user when there isn't enough memory."""
    return tr("There isn't enough free memory for the local model "
              "(it needs about {needed} GB, {free} GB free). Close some "
              "apps and try again.").format(needed="%.1f" % (MODEL_GB + MARGIN_GB),
                                            free="%.1f" % available_memory_gb())
