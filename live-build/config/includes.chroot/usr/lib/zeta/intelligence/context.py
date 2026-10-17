# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence: what every request tells the model besides the chat.

A language model does not know what day it is, and what it learned stops at
its training date. Asked «who is the president of …» it answers with whoever
held the office back then, as if it were today (observed: on 17 October 2026
the local model named a president who had left office). So every request, to
every provider, carries:

  1. the current local date, time and time zone;
  2. a short rule: facts that change over time are not presented as current
     unless they come from the sources in the prompt;
  3. the sources found on the web, when the user allowed the lookup.

The text is in English and short on purpose: small local models follow short
English instructions best, and every word costs time on a slow computer.
"""
from __future__ import annotations

import os
from datetime import datetime

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def local_zone_name() -> str:
    """The time zone name (Europe/Rome), or "" if it can't be found."""
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz and not tz.startswith("/"):
        return tz
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        with open("/etc/timezone") as f:
            return f.read().strip()
    except OSError:
        return ""


def now_line(now: datetime | None = None) -> str:
    """«Current local date and time: Saturday 17 October 2026, 14:05 …»."""
    now = (now or datetime.now()).astimezone()
    offset = now.strftime("%z") or "+0000"
    offset = "UTC%s:%s" % (offset[:3], offset[3:])
    zone = local_zone_name() or now.tzname() or ""
    zone_text = "%s, %s" % (zone, offset) if zone and zone != offset else offset
    return ("Current local date and time: %s %d %s %d, %02d:%02d (time zone %s). "
            "Today's date is %s." % (_WEEKDAYS[now.weekday()], now.day, _MONTHS[now.month - 1],
                                     now.year, now.hour, now.minute, zone_text,
                                     now.date().isoformat()))


GUIDANCE = (
    "Your knowledge comes from training data that ends at a past date. Facts that change "
    "over time (who holds an office, news, prices, software versions, weather, sports "
    "results) may have changed since then: never present them as current unless they "
    "appear in the Sources below. Any date before today's date is in the past: events "
    "scheduled for it have already happened, even when your training data does not know "
    "their outcome.")

# What to do with a time-sensitive question, depending on the web lookup
_WEB = {
    # Measured on 17 October 2026 with the local 4B model: with a softer rule
    # it answered "not awarded yet" about a prize given a year earlier when
    # the sources did not mention it; with this one it says that the sources
    # do not say, and still answers from the sources when they do.
    "sources": (
        "Answer only with facts stated in the Sources, citing them as [1], [2]. If the "
        "Sources do not state the answer, reply that the sources found do not say it, and "
        "suggest checking elsewhere. Never say that something has not happened yet: dates "
        "before today are in the past."),
    "off": (
        "This question is about current facts and web search is off. In the user's language, "
        "begin your reply by saying that you cannot verify what is true today. Then you may give "
        "what your training data says, clearly introduced as possibly out of date. Do not call "
        "it current."),
    "failed": (
        "This question is about current facts and the web search found no useful source (or the "
        "network is unavailable). In the user's language, begin your reply by saying that you "
        "cannot verify what is true today. Then you may give what your training data says, "
        "clearly introduced as possibly out of date. Do not call it current."),
    "provider": "You search the web yourself: say where current facts come from.",
    "": "If you cannot verify a current fact, say so and offer to search the web.",
}


def format_sources(sources, retrieved: str = "") -> str:
    """The «Sources» block: number, title, address and the useful excerpt."""
    if not sources:
        return ""
    day = retrieved or (sources[0].retrieved if getattr(sources[0], "retrieved", "") else "")
    lines = ["Sources (retrieved from the web on %s):" % day if day else "Sources (from the web):"]
    for i, s in enumerate(sources, 1):
        lines.append("[%d] %s - %s" % (i, s.title, s.url))
        if s.snippet:
            lines.append(s.snippet)
    return "\n".join(lines)


_LANGUAGES = {"it": "Italian", "en": "English"}


def system_prompt(base: str, *, web: str = "", sources=None, now: datetime | None = None,
                  reply_language: str = "", always_language: str = "") -> str:
    """The full system prompt for one request.

    `base` is the persona (the default one or the user's own, from Settings
    › AI): the date and the rules are added in any case, so a custom prompt
    cannot leave the model without them.
    `web`: "" (not a time-sensitive question), "sources", "off", "failed",
    "provider" (the service searches the web by itself).
    `always_language`: English name of the language every reply must use
    (Settings › AI › Reply language set to the system language), else "".
    """
    # Fixed text first, changing text last: Ollama reuses the work already
    # done on an identical beginning of the prompt (prefix cache), which on a
    # slow processor saves seconds per question. The clock changes every
    # minute, so it comes after the fixed rules.
    parts = [base.strip(), GUIDANCE, _WEB.get(web, _WEB[""]), now_line(now)]
    block = format_sources(sources or [])
    if block:
        parts.append(block)
    # Long English instructions pull small models into English: when the
    # question's language is clear, say it last (observed with a 4B model).
    if always_language:
        # Settings › AI › Reply language: always the system language
        parts.append("Always reply in %s, whatever language the user writes in." % always_language)
    elif reply_language in _LANGUAGES:
        parts.append("The user writes in %s: reply in %s." % ((_LANGUAGES[reply_language],) * 2))
    return "\n\n".join(p for p in parts if p)
