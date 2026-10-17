# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence: looking up current facts on the web (opt-in).

A model cannot know who holds an office today, a price or a result: what it
learned stops at its training date. Benchmarks on 3B-class local models
showed that with a short excerpt and its source in the prompt they answer
correctly; without it they state stale facts as current.

Privacy rules (also in PRIVACY.md):
  • OFF by default. The first time a time-sensitive question is asked, ZETA
    asks (Yes / Always / No); the switch is in Settings › AI.
  • Only for time-sensitive questions (office holders, news, prices,
    versions, weather, results), recognized below.
  • Only the question is sent, shortened to its key words: never the chat
    history, never files, never anything else.
  • Only public APIs without a key: Wikipedia (search + page extract) and,
    if the user also turns it on, DuckDuckGo Instant Answer. No scraping of
    search result pages.
  • 5-second limit, size limit, no cookies, a clear User-Agent.
"""
from __future__ import annotations

import re
import threading
import time
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date

from i18n_data import load

from .providers.base import CancelToken, Canceled, get_json

# The Italian and English words and patterns below are language data:
# websearch.json (see i18n_data.py)
_DATA = load("websearch")

SETTING_ENABLED = "web_lookup"            # bool, default False
SETTING_DECLINED = "web_lookup_declined"  # «No» to the one-time question: don't ask again
SETTING_DDG = "web_lookup_ddg"            # also DuckDuckGo Instant Answer, default False

TIMEOUT = 5.0                 # seconds per service
MAX_BYTES = 512 * 1024        # a reply larger than this is discarded
MAX_SOURCES = 3
SNIPPET_CHARS = 700
USER_AGENT = "ZETA-RAYS-OS/2.1 (https://zetarays.org; ZETA assistant web lookup)"
_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


@dataclass
class Source:
    title: str
    url: str
    snippet: str
    retrieved: str            # ISO date of the lookup
    site: str = ""


# --------------------------------------------------------------- settings
def enabled(settings: dict) -> bool:
    return bool(settings.get(SETTING_ENABLED, False))


def mode(settings: dict) -> str:
    """"on", "ask" (never answered: ask once) or "off"."""
    if enabled(settings):
        return "on"
    return "off" if settings.get(SETTING_DECLINED) else "ask"


def services(settings: dict) -> list[str]:
    """The services the question would be sent to."""
    return ["Wikipedia"] + (["DuckDuckGo"] if settings.get(SETTING_DDG) else [])


def save_choice(choice: str) -> None:
    """The answer to «Search the web?»: "always" turns the lookup on, "no"
    stops the question from coming back, "yes" is for this question only."""
    from .registry import load_settings, save_settings
    s = load_settings()
    if choice == "always":
        s[SETTING_ENABLED] = True
        s.pop(SETTING_DECLINED, None)
    elif choice == "no":
        s[SETTING_DECLINED] = True
    else:
        return
    save_settings(s)


# ------------------------------------------------- time-sensitive questions
# The patterns name the offices ({offices}), news, prices, software versions
# and releases, weather, sports results and elections.
_OFFICES = _DATA["offices"]
_PATTERNS = [p.replace("{offices}", _OFFICES) for p in _DATA["patterns"]]
# questions answered by the clock in the prompt, not by the web
_CLOCK = _DATA["clock"]
# words meaning "now" that keep a question current even when it names a year
_NOW_WORDS = _DATA["now_words"]
_RX = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]
_RX_CLOCK = re.compile(_CLOCK, re.IGNORECASE)
_RX_NOW = re.compile(_NOW_WORDS, re.IGNORECASE)
_RX_YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


def is_time_sensitive(text: str, today: date | None = None) -> bool:
    """True for questions whose answer can change over time."""
    t = (text or "").strip()
    if len(t) < 6 or _RX_CLOCK.search(t):
        return False
    if not any(rx.search(t) for rx in _RX):
        return False
    # «who won the 1998 World Cup»: about the past, the model may know it
    year = (today or date.today()).year
    years = [int(y) for y in _RX_YEAR.findall(t)]
    if years and max(years) < year - 1 and not _RX_NOW.search(t):
        return False
    return True


# Italian and English words dropped from a search query
_STOP = set(_DATA["stop_words"])


def make_query(text: str, max_words: int = 8) -> str:
    """The question reduced to its key words: shorter, and nothing personal
    beyond what the user asked."""
    t = re.sub(r"[\"“”«»?!.,;:()\[\]{}]", " ", text or "")
    t = re.sub(r"\b([A-Za-z]{1,3})['’]", r"\1 ", t)          # elided article: split it off
    words = [w for w in t.split() if w.lower() not in _STOP]
    return " ".join(words[:max_words])[:100]


# Italian words that reveal an Italian question
_IT_HINT = re.compile(_DATA["it_hint"])
_EN_HINT = re.compile(r"(?i)\b(?:who|what|which|how|when|where|why|is|are|the|of|today|current|"
                      r"a|an|my|your|you|i|me|write|please|this|that|with|and|for|tell|can|do)\b")


def clear_language(text: str) -> str:
    """"it" or "en" when the question clearly is in that language, else ""."""
    it, en = len(_IT_HINT.findall(text or "")), len(_EN_HINT.findall(text or ""))
    if it >= 1 and it > en:
        return "it"
    if en >= 1 and en > it:
        return "en"
    return ""


def question_language(text: str, default: str = "en") -> str:
    """"it" or "en" (the two Wikipedias used); other languages: the default
    if it is one of them, else English."""
    it, en = len(_IT_HINT.findall(text or "")), len(_EN_HINT.findall(text or ""))
    if it > en:
        return "it"
    if en > it:
        return "en"
    return default if default in ("it", "en") else "en"


# ------------------------------------------------------------- the lookup
# A few recent answers, so that asking the same thing twice does not query
# the services again. Bounded in size and in time.
_CACHE: "OrderedDict[tuple, tuple[float, list[Source]]]" = OrderedDict()
_CACHE_SIZE = 32
_CACHE_TTL = 600.0
_cache_lock = threading.Lock()

# words that mark a sentence about the present
_CURRENT = re.compile(_DATA["current"])


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý0-9«“\"(])", text) if s]


def best_excerpt(extract: str, query: str, limit: int = SNIPPET_CHARS) -> str:
    """The definition (first sentence) plus the sentences that best match the
    question, preferring those about the present («the current president
    is …», usually far from the start of the article)."""
    sents = _sentences(extract)
    if not sents:
        return ""
    stems = {w.lower()[:5] for w in query.split() if len(w) > 2}
    scored = []
    for i, s in enumerate(sents[1:], 1):
        low = s.lower()
        score = sum(1 for st in stems if st in low)
        if score and _CURRENT.search(s):
            score += 2
        if score:
            scored.append((score, i))
    # best sentences first, as long as they fit; then back in article order
    room = limit - len(sents[0])
    chosen = []
    for _score, i in sorted(scored, key=lambda x: (-x[0], x[1])):
        if len(chosen) == 2:
            break
        if len(sents[i]) + 3 <= room:
            chosen.append(i)
            room -= len(sents[i]) + 3
    chosen.sort()
    out, last = sents[0], 0
    for i in chosen:
        sep = " " if i == last + 1 else " … "
        if len(out) + len(sep) + len(sents[i]) > limit:
            break
        out += sep + sents[i]
        last = i
    return out[:limit]


_LANG_OK = re.compile(r"^[a-z]{2,3}$")


def _wikipedia(query: str, lang: str, token: CancelToken | None, limit: int) -> list[Source]:
    if not _LANG_OK.match(lang):
        lang = "en"
    params = {"action": "query", "format": "json", "formatversion": "2", "generator": "search",
              "gsrsearch": query, "gsrlimit": str(limit), "prop": "extracts|info", "exintro": "1",
              "explaintext": "1", "exlimit": str(limit), "inprop": "url", "redirects": "1"}
    url = "https://%s.wikipedia.org/w/api.php?%s" % (lang, urllib.parse.urlencode(params))
    data = get_json(url, _HEADERS, timeout=TIMEOUT, max_bytes=MAX_BYTES, token=token)
    pages = (data.get("query") or {}).get("pages") or [] if isinstance(data, dict) else []
    today = date.today().isoformat()
    stems = {w.lower()[:5] for w in query.split() if len(w) > 2}
    out = []
    for p in sorted(pages, key=lambda p: p.get("index", 99)):
        title, link = str(p.get("title", ""))[:200], str(p.get("fullurl", ""))
        if not title or not link.startswith("https://"):
            continue
        # after the top result, only pages that share most of the key words
        # (a search for the president also returns unrelated US articles)
        text = (title + " " + p.get("extract", "")[:3000]).lower()
        if out and stems and sum(1 for st in stems if st in text) < 0.6 * len(stems):
            continue
        out.append(Source(title=title, url=link, snippet=best_excerpt(p.get("extract", ""), query),
                          retrieved=today, site="%s.wikipedia.org" % lang))
    return out


def _duckduckgo(query: str, token: CancelToken | None) -> list[Source]:
    params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1",
              "no_redirect": "1", "t": "zetarays"}
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(params)
    data = get_json(url, _HEADERS, timeout=TIMEOUT, max_bytes=MAX_BYTES, token=token)
    if not isinstance(data, dict):
        return []
    text = str(data.get("AbstractText") or data.get("Answer") or "").strip()
    link = str(data.get("AbstractURL") or "")
    if not text or not link.startswith("https://"):
        return []
    title = str(data.get("Heading") or data.get("AbstractSource") or "DuckDuckGo")[:200]
    return [Source(title=title, url=link, snippet=text[:SNIPPET_CHARS],
                   retrieved=date.today().isoformat(), site="duckduckgo.com")]


def lookup(text: str, settings: dict, lang: str = "en",
           token: CancelToken | None = None) -> tuple[list[Source], bool]:
    """(sources, reachable). reachable False = every service failed (offline,
    timeout): the caller says that current facts can't be verified."""
    query = make_query(text)
    if not query:
        return [], True
    lang = question_language(text, lang)
    use_ddg = bool(settings.get(SETTING_DDG))
    key = (query.lower(), lang, use_ddg)
    now = time.monotonic()
    with _cache_lock:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            _CACHE.move_to_end(key)
            return list(hit[1]), True

    results: dict = {}
    failures: list = []

    def run(name, fn, *args):
        try:
            results[name] = fn(*args)
        except Canceled:
            failures.append(name)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            failures.append(name)

    jobs = [threading.Thread(target=run, args=("wiki", _wikipedia, query, lang, token, 2), daemon=True)]
    if use_ddg:
        jobs.append(threading.Thread(target=run, args=("ddg", _duckduckgo, query, token), daemon=True))
    for j in jobs:
        j.start()
    for j in jobs:
        j.join(TIMEOUT * 2 + 1)
    if token is not None and token.canceled:
        raise Canceled()
    sources = list(results.get("wiki", []))
    # nothing in the question's language: the English Wikipedia
    if not sources and lang != "en" and "wiki" in results:
        run("wiki_en", _wikipedia, query, "en", token, 2)
        sources = list(results.get("wiki_en", []))
    sources += results.get("ddg", [])
    # same page from two services: keep one
    seen, unique = set(), []
    for s in sources:
        if s.url not in seen:
            seen.add(s.url)
            unique.append(s)
    unique = unique[:MAX_SOURCES]
    reachable = bool(results) or not failures
    if reachable:
        with _cache_lock:
            _CACHE[key] = (now, unique)
            _CACHE.move_to_end(key)
            while len(_CACHE) > _CACHE_SIZE:
                _CACHE.popitem(last=False)
    return unique, reachable
