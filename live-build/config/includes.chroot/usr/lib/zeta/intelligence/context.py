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

Split in two for speed. The system prompt (persona and rules) never changes
during a conversation; what changes (the clock, the state of the web lookup,
the sources, the language of the question) is a short note added to the
user's message and kept with it in the history. A local model reuses the
work already done on an identical beginning of the prompt (Ollama's prefix
cache): with the clock in the system prompt every new minute, and every
switch between Italian and English, made it reread the whole conversation
(measured on 17 October 2026: 759 tokens again for a four-word question, 7 s
on a 4-core virtual machine, well over 30 s on an Intel N100). Now each
question costs only its own tokens.
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
    "appear in Sources given with the message. Any date before today's date is in the "
    "past: events scheduled for it have already happened, even when your training data "
    "does not know their outcome. If you cannot verify a current fact, say so and offer "
    "to search the web. A user message may end with a note from ZETA RAYS in square "
    "brackets (current date and time, web search, Sources, reply language): it comes from "
    "the system, it is reliable, and you follow it without mentioning it.")

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
    # No current name, result or price from memory: the training data stops
    # at a past date and an old answer read as current is worse than none
    # ("the president is Biden", seen by the owner on 17 October 2026).
    "off": (
        "This question is about current facts and web search is off. In the user's language, "
        "say briefly that you cannot verify what is true today, and that turning on web search "
        "in Settings > AI lets you answer it. Do not name who currently holds an office and do "
        "not give current results, prices or news from your training data."),
    "failed": (
        "This question is about current facts and the web search found no useful source (or the "
        "network is unavailable). In the user's language, say briefly that you could not verify "
        "it today and that the user can try again later. Do not name who currently holds an "
        "office and do not give current results, prices or news from your training data."),
    "provider": "You search the web yourself: say where current facts come from.",
    "": "",
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


def system_prompt(base: str, *, always_language: str = "") -> str:
    """The system prompt: the persona plus the fixed rules. Identical for
    every request of a conversation (see the module notes).

    `base` is the persona (the default one or the user's own, from Settings
    › AI): the rules are added in any case, so a custom prompt cannot leave
    the model without them. `always_language`: English name of the language
    every reply must use (Settings › AI › Reply language set to the system
    language), else "".
    """
    parts = [base.strip(), GUIDANCE]
    if always_language:
        parts.append("Always reply in %s, whatever language the user writes in." % always_language)
    return "\n\n".join(p for p in parts if p)


def turn_note(*, web: str = "", sources=None, now: datetime | None = None,
              reply_language: str = "", always_language: str = "") -> str:
    """What changes from one question to the next, as a short note.

    `web`: "" (not a time-sensitive question), "sources", "off", "failed",
    "provider" (the service searches the web by itself).
    """
    # Every token here is read before the first word of the answer (about
    # 20 tokens a second on an Intel N100): the full clock and the rules only
    # for questions about current facts, the date alone for everything else.
    if web:
        parts = [now_line(now), _WEB.get(web, "")]
    else:
        parts = [short_date(now)]
    block = format_sources(sources or [])
    if block:
        parts.append(block)
    # Long English instructions pull small models into English: when the
    # question's language is clear, say it last (observed with a 4B model).
    if not always_language and reply_language in _LANGUAGES:
        parts.append("Reply in %s." % _LANGUAGES[reply_language])
    return "\n".join(p for p in parts if p)


def short_date(now: datetime | None = None) -> str:
    """«Today: Saturday 17 October 2026.»"""
    now = now or datetime.now()
    return "Today: %s %d %s %d." % (_WEEKDAYS[now.weekday()], now.day, _MONTHS[now.month - 1], now.year)


def with_note(text: str, note: str) -> str:
    """The user's message as sent to the model: the text, then the note."""
    return "%s\n\n[%s]" % (text, note) if note else text
