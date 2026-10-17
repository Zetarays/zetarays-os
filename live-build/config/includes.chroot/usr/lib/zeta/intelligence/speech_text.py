# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — text normalization before speech synthesis.

Piper reads what it is given, letter by letter if needed: "14:30", "23%",
"3,5 GB", "**bold**", a URL or an emoji come out as noise or as a spelled
string. normalize() turns a reply into the words a person would say, in
Italian or in English:

- Markdown and code are removed (the reply on screen keeps them),
- URLs become the site name, e-mail addresses are read out,
- emoji and decorative symbols disappear,
- numbers, times, dates, percentages, units, currencies, ordinals and common
  abbreviations become words,
- a few English words the Italian voice gets wrong get an Italian-friendly
  spelling, so it says them the way Italians do ("Firefox", "Google", "file").

The Italian words (numbers, months, units, abbreviations, pronunciations) are
language data in speech_text.json (see i18n_data.py).

Pure functions, no dependencies beyond i18n_data: tools/voice-bench imports it
outside the desktop too.
"""
from __future__ import annotations

import re
import unicodedata

from i18n_data import load

_DATA = load("speech_text")

# --------------------------------------------------------------- numbers
_IT = _DATA["it_numbers"]
_IT_UNITS = _IT["units"]
_IT_TENS = {int(k): v for k, v in _IT["tens"].items()}
_IT_ORD = _IT["ordinals"]
_IT_MONTHS = _IT["months"]
_IT_ART = _DATA["it_articles"]
_EN_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
             "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
             "seventeen", "eighteen", "nineteen"]
_EN_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy",
            8: "eighty", 9: "ninety"}
_EN_ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth",
           "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}
_EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December"]


def _it_below_100(n: int) -> str:
    if n < 20:
        return _IT_UNITS[n]
    t, u = divmod(n, 10)
    word = _IT_TENS[t]
    if u in (1, 8):                   # the tens lose their last vowel before 1 and 8
        word = word[:-1]
    return word + (_IT_UNITS[u] if u else "")


def _it_below_1000(n: int) -> str:
    h, r = divmod(n, 100)
    out = ""
    if h:
        out = _IT["hundred"] if h == 1 else _IT_UNITS[h] + _IT["hundred"]
    if r:
        rest = _it_below_100(r)
        if h and rest.startswith("o"):  # elision before 8 and 80-89
            out = out[:-1]
        out += rest
    return out


def it_cardinal(n: int) -> str:
    """Italian words for a whole number (masculine), e.g. for 2026."""
    if n < 0:
        return _WORDS["it"]["minus"] + " " + it_cardinal(-n)
    if n == 0:
        return _IT_UNITS[0]
    if n >= 10 ** 12:
        return " ".join(_IT_UNITS[int(d)] for d in str(n))
    parts = []
    billions, n = divmod(n, 10 ** 9)
    millions, n = divmod(n, 10 ** 6)
    thousands, n = divmod(n, 1000)
    if billions:
        parts.append(_IT["billion"] if billions == 1 else it_cardinal(billions) + " " + _IT["billions"])
    if millions:
        parts.append(_IT["million"] if millions == 1 else it_cardinal(millions) + " " + _IT["millions"])
    word = ""
    if thousands:
        word = _IT["thousand"] if thousands == 1 else _it_below_1000(thousands) + _IT["thousands_suffix"]
    if n:
        word += _it_below_1000(n)
    if word:
        parts.append(word)
    out = " ".join(parts)
    three, accented = _IT["final_three"]
    if out.endswith(three) and out != three:
        out = out[:-len(three)] + accented   # a final 3 takes an accent in compounds
    return out


def it_ordinal(n: int, feminine: bool = False) -> str:
    if 0 < n <= 10:
        word = _IT_ORD[n]
    else:
        base = it_cardinal(n)
        suffix = _IT["ordinal_suffix"]
        accent, plain = _IT["ordinal_accent"]
        if base.endswith(accent):     # the accented final 3 loses its accent
            word = base[:-len(accent)] + plain + suffix
        elif base.endswith(_IT["ordinal_keep"]):  # a final 6 keeps its last vowel
            word = base + suffix
        else:
            word = base[:-1] + suffix
    return word[:-1] + _IT["feminine_ending"] if feminine else word


def _en_below_1000(n: int) -> str:
    h, r = divmod(n, 100)
    parts = []
    if h:
        parts.append(_EN_UNITS[h] + " hundred")
    if r:
        if r < 20:
            parts.append(_EN_UNITS[r])
        else:
            t, u = divmod(r, 10)
            parts.append(_EN_TENS[t] + (" " + _EN_UNITS[u] if u else ""))
    return " ".join(parts)


def en_cardinal(n: int) -> str:
    if n < 0:
        return "minus " + en_cardinal(-n)
    if n == 0:
        return "zero"
    if n >= 10 ** 12:
        return " ".join(_EN_UNITS[int(d)] for d in str(n))
    parts = []
    for size, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        q, n = divmod(n, size)
        if q:
            parts.append(_en_below_1000(q) + " " + name)
    if n:
        parts.append(_en_below_1000(n))
    return " ".join(parts)


def en_ordinal(n: int) -> str:
    words = en_cardinal(n).split(" ")
    last = words[-1]
    if last in _EN_ORD:
        last = _EN_ORD[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return " ".join(words[:-1] + [last])


def en_year(n: int) -> str:
    if 1100 <= n <= 1999 or 2010 <= n <= 2099:
        hi, lo = divmod(n, 100)
        if lo == 0:
            return en_cardinal(hi) + " hundred"
        return en_cardinal(hi) + (" oh " if lo < 10 else " ") + en_cardinal(lo)
    return en_cardinal(n)


def cardinal(n: int, lang: str) -> str:
    return it_cardinal(n) if lang == "it" else en_cardinal(n)


# ----------------------------------------------------------- word tables
# {language: {unit: [singular, plural]}} of the units that follow a number
_UNITS = _DATA["units"]
# {language: {name: word}}: readings of symbols and abbreviations
_WORDS = _DATA["words"]
# {language: [[pattern, words], ...]}: abbreviations, matched ignoring case
_ABBREVIATIONS = _DATA["abbreviations"]

# How the Italian voice should say English and technical words. The Italian
# voice reads with espeak-ng's Italian rules, which already know many English
# words (computer, password, download, Wi-Fi, Bluetooth...): only the words it
# gets wrong are in the data file, each one checked with tools/voice-bench
# (espeak-ng phonemes, and an Italian speech recognizer must understand the new
# spelling at least as well). Accented vowels mark the stress. The acronyms
# are matched only in capitals (their lowercase form can be an Italian word).
_IT_LEXICON = _DATA["it_lexicon"]
_IT_ACRONYMS = _DATA["it_acronyms"]
_EN_LEXICON = {"ok": "okay"}
_EN_ACRONYMS = {"AI": "A I"}

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U0000200D\U000020E3]")


# --------------------------------------------------------------- passes
def _strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?(```|$)", " ", text, flags=re.S)      # code blocks
    text = re.sub(r"`([^`]*)`", r"\1", text)                     # inline code
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)        # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)         # links
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r"\|?[\s:|-]+\|?", s) and "-" in s:     # table rule
            continue
        if s.startswith("|"):
            s = ", ".join(c.strip() for c in s.strip("|").split("|") if c.strip())
        s = re.sub(r"^#{1,6}\s+", "", s)                         # headings
        s = re.sub(r"^>\s?", "", s)                              # quotes
        s = re.sub(r"^(?:[-*+•]|\d+[.)])\s+", "", s)             # list items
        if s and not re.search(r"[.!?:;,…]$", s):
            s += "."                                             # a pause per line
        lines.append(s)
    text = " ".join(x for x in lines if x)
    text = re.sub(r"(\*\*|__|~~)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])[*_](?=\S)(.+?)(?<=\S)[*_](?![\w*])", r"\1", text)
    return text


def _domain(host: str, lang: str) -> str:
    host = re.sub(r"^www\.", "", host.lower())
    return (" %s " % _WORDS[lang]["point"]).join(host.split("."))


def _urls(text: str, lang: str) -> str:
    def url(m):
        return _domain(m.group(1), lang)
    text = re.sub(r"\bhttps?://([\w.-]+)(?::\d+)?[^\s)\]>]*", url, text)
    text = re.sub(r"\bwww\.([\w-]+(?:\.[\w-]+)+)[^\s)\]>]*", url, text)

    def email(m):
        return "%s %s %s" % (m.group(1).replace(".", " %s " % _WORDS[lang]["point"]),
                             _WORDS[lang]["at"], _domain(m.group(2), lang))
    text = re.sub(r"\b([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)", email, text)
    text = re.sub(r"\b([\w-]+(?:\.[\w-]+)*\.(?:com|org|net|it|io|dev|eu|edu|gov|info|app))\b",
                  lambda m: _domain(m.group(1), lang), text)
    return text


def _symbols(text: str, lang: str) -> str:
    w = _WORDS[lang]
    text = text.replace("…", "...").replace(" ", " ").replace(" ", " ")
    text = re.sub(r"[“”«»„\"]", "", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"\s*[→⇒➜►▶]\s*", ", ", text)
    text = re.sub(r"\s*[•·|]\s*", ", ", text)
    text = re.sub(r"\s+[-–—]\s+", ", ", text)                    # dashes as pauses
    text = re.sub(r"\s*&\s*", " %s " % w["and"], text)
    text = re.sub(r"(?<=[\d\s])\+(?=[\s\d])", " %s " % w["plus"], text)
    text = re.sub(r"\s=\s", " %s " % w["equals"], text)
    text = re.sub(r"(?<=\d)\s?[x×]\s?(?=\d)", " %s " % w["times"], text)
    text = re.sub(r"#(?=\d)", w["number"] + " ", text)
    text = re.sub(r"~\s?(?=\d)", w["about"] + " ", text)
    text = re.sub(r"(?<![\w-])-(?=\d)", w["minus"] + " ", text)  # negative numbers
    text = _EMOJI.sub(" ", text)
    text = "".join(c for c in text if c == "°" or unicodedata.category(c) not in ("So", "Cs", "Co"))
    text = re.sub(r"[*_^\\{}\[\]<>]", " ", text)
    text = re.sub(r"[()]", ", ", text)
    return text


def _abbreviations(text: str, lang: str) -> str:
    for pattern, words in _ABBREVIATIONS[lang]:
        text = re.sub(pattern, words, text, flags=re.I)
    return text


# an hour written with a dot after the words that introduce a time
_IT_DOT_TIME = _IT["dot_time"]


def _it_time(h: int, m: int) -> str:
    if h == 0 and m == 0:
        return _IT["midnight"]
    hour = it_cardinal(h).replace(*_IT["hour_one"]) if h in (1, 21) else it_cardinal(h)
    return hour if m == 0 else "%s %s %s" % (hour, _WORDS["it"]["and"], it_cardinal(m))


def _en_time(h: int, m: int, suffix: str) -> str:
    out = en_cardinal(h)
    if m:
        out += (" oh " if m < 10 else " ") + en_cardinal(m)
    elif not suffix:
        out += " o'clock" if h <= 12 else " hundred"
    return out + (" " + " ".join(suffix.replace(".", "").upper()) if suffix else "")


def _date(d: int, m: int, y, lang: str) -> str:
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return ""
    if lang == "it":
        out = "%s %s" % (it_ordinal(1) if d == 1 else it_cardinal(d), _IT_MONTHS[m - 1])
        return out + (" " + it_cardinal(y) if y is not None else "")
    out = "%s %s" % (_EN_MONTHS[m - 1], en_ordinal(d))
    return out + (", " + en_year(y) if y is not None else "")


def _times_dates(text: str, lang: str) -> str:
    def iso(m):
        return _date(int(m.group(3)), int(m.group(2)), int(m.group(1)), lang) or m.group(0)
    text = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", iso, text)

    def slash(m):
        a, b = int(m.group(1)), int(m.group(2))
        y = m.group(3)
        if y is not None:
            y = int(y) + (2000 if len(y) == 2 else 0)
        if lang == "en" and a <= 12:
            a, b = b, a                       # US order: month/day
        return _date(a, b, y, lang) or m.group(0)
    text = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b(?!/)", slash, text)

    if lang == "it":
        text = re.sub(r"\b(1|1°|1º)\s+(?=(%s)\b)" % "|".join(_IT_MONTHS), it_ordinal(1) + " ", text, flags=re.I)

        def it_time(m):
            return _it_time(int(m.group(1)), int(m.group(2)))
        text = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\b", it_time, text)
        # a dot works as a time separator after the words of _IT_DOT_TIME
        text = re.sub(_IT_DOT_TIME,
                      lambda m: m.group(1) + _it_time(int(m.group(2)), int(m.group(3))), text, flags=re.I)
    else:
        def en_time(m):
            return _en_time(int(m.group(1)), int(m.group(2)), m.group(3) or "")
        text = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?(?:\s?([ap]\.?m\.?)(?![a-z]))?",
                      en_time, text, flags=re.I)
        text = re.sub(r"\b(1[0-2]|[1-9])\s?([ap]\.?m\.?)(?![a-z])",
                      lambda m: _en_time(int(m.group(1)), 0, m.group(2)), text, flags=re.I)
    return text


_NUMBER = r"\d+(?:[.,]\d+)*"


def _number_words(token: str, lang: str) -> str:
    """Words for a number as written: 3,5 / 1.000 / 2.1.4 / 1,234.56."""
    w = _WORDS[lang]
    if lang == "it":
        thousands, decimal = ".", ","
    else:
        thousands, decimal = ",", "."
    if re.fullmatch(r"\d{1,3}(?:\%s\d{3})+(?:\%s\d+)?" % (thousands, decimal), token):
        token = token.replace(thousands, "")
    if token.count(decimal) == 1 and token.replace(decimal, "").isdigit():
        whole, frac = token.split(decimal)
        # Italian: up to two decimals read as one number ("comma fifty");
        # English: digit by digit ("three point five six")
        frac_words = (" ".join(cardinal(int(c), lang) for c in frac)
                      if lang != "it" or frac.startswith("0") or len(frac) > 2
                      else cardinal(int(frac), lang))
        return "%s %s %s" % (cardinal(int(whole), lang), w["comma"] if lang == "it" else w["point"],
                             frac_words)
    if token.isdigit():
        if len(token) > 1 and token.startswith("0"):
            return " ".join(cardinal(int(c), lang) for c in token)   # codes, PINs
        return cardinal(int(token), lang)
    # versions and addresses: 2.1, 192.168.1.1
    parts = re.split(r"[.,]", token)
    return (" %s " % w["point"]).join(cardinal(int(p), lang) if not p.startswith("0") or p == "0"
                                      else " ".join(cardinal(int(c), lang) for c in p)
                                      for p in parts if p)


def _is_one(token: str) -> bool:
    return token == "1"


def _numbers(text: str, lang: str) -> str:
    units = _UNITS[lang]
    w = _WORDS[lang]
    text = re.sub(r"\bv(?=\d+\.\d)", w["version"] + " ", text)
    unit_names = sorted(units, key=len, reverse=True)
    unit_re = "|".join(re.escape(u) for u in unit_names)

    def unit_after(m):
        number, unit = m.group(1), m.group(2)
        singular, plural = units[unit]
        name = singular if _is_one(number) else plural
        if lang == "it" and _is_one(number):
            article = _IT_ART["feminine"] if name.endswith(_IT_ART["feminine_ending"]) else _IT_ART["masculine"]
            return article + " " + name
        return "%s %s" % (_number_words(number, lang), name)
    if lang == "en":                  # $1,234.56 -> ... dollars and fifty six cents
        def money(m):
            whole = int(m.group(2).replace(",", ""))
            cents = int(m.group(3))
            unit = units[m.group(1)][0 if whole == 1 else 1]
            out = "%s %s" % (en_cardinal(whole), unit)
            if cents:
                out += " and %s %s" % (en_cardinal(cents), "cent" if cents == 1 else "cents")
            return out
        text = re.sub(r"([€$£])\s?(\d{1,3}(?:,\d{3})*|\d+)\.(\d{2})(?!\d)", money, text)
    # currency before the number: €5, $ 10
    text = re.sub(r"([€$£])\s?(%s)" % _NUMBER,
                  lambda m: "%s %s" % (_number_words(m.group(2), lang),
                                       units[m.group(1)][0 if _is_one(m.group(2)) else 1]), text)
    text = re.sub(r"(%s)\s?%%" % _NUMBER,
                  lambda m: "%s %s" % (_number_words(m.group(1), lang), w["percent"]), text)
    text = re.sub(r"(?<![\w.,])(%s)\s?(%s)(?![\w])" % (_NUMBER, unit_re), unit_after, text)
    # ordinals: 1°, 3ª (Italian), 1st, 22nd (English)
    if lang == "it":
        # (a plain "°" after a number means degrees: handled with the units)
        text = re.sub(r"\b(\d+)([ºª])",
                      lambda m: it_ordinal(int(m.group(1)), m.group(2) == "ª"), text)
    else:
        text = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: en_ordinal(int(m.group(1))), text)
        text = re.sub(r"\b(?:in|of|since|from|until|by)\s+(1[1-9]\d\d|20\d\d)\b(?![.,]\d)",
                      lambda m: m.group(0).split()[0] + " " + en_year(int(m.group(1))), text)

    def plain(m):
        token = m.group(1)
        if lang == "it" and token == "1":
            # "1" before a word is the article, which agrees with that word
            following = text[m.end():].lstrip()
            word = re.match(_IT_ART["word"], following, re.I)
            if word:
                nxt = word.group(0).lower()
                if nxt.endswith(_IT_ART["feminine_ending"]):
                    return _IT_ART["elided"] if nxt[0] in _IT_ART["vowels"] else _IT_ART["feminine"]
                if re.match(_IT_ART["strong_start"], nxt):
                    return _IT_ART["masculine_strong"]
                return _IT_ART["masculine"]
        return _number_words(token, lang)
    text = re.sub(r"(?<![\w])(%s)(?![\w])" % _NUMBER, plain, text)
    text = re.sub(_IT_ART["elided_space"], _IT_ART["elided"], text)
    # whatever digits are left (stuck to letters, like "mp3" or "x86"): read them
    text = re.sub(r"\d+", lambda m: " " + _number_words(m.group(0), lang) + " ", text)
    return text


def _lexicon(text: str, lang: str) -> str:
    words, acronyms = (_IT_LEXICON, _IT_ACRONYMS) if lang == "it" else (_EN_LEXICON, _EN_ACRONYMS)
    for table, flags in ((words, re.I), (acronyms, 0)):
        if not table:
            continue
        keys = sorted(table, key=len, reverse=True)
        pattern = re.compile(r"(?<![\w-])(%s)(?![\w-])" % "|".join(re.escape(k) for k in keys), flags)
        text = pattern.sub(lambda m, t=table, f=flags: t[m.group(1).lower() if f else m.group(1)], text)
    return text


def normalize(text: str, lang: str = "it", lexicon: bool = True) -> str:
    """The words to say for a reply shown on screen, in "it" or "en"
    (other languages: everything except number and word readings)."""
    base = (lang or "en").split("_")[0].lower()
    full = base in ("it", "en")
    text = _strip_markdown(text or "")
    if full:
        text = _urls(text, base)
        text = _symbols(text, base)
    else:                             # espeak-ng reads symbols in its own language
        text = re.sub(r"\bhttps?://(?:www\.)?([\w.-]+)[^\s)\]>]*", r"\1", text)
        text = _EMOJI.sub(" ", text)
    if full:
        text = _abbreviations(text, base)
        text = _times_dates(text, base)
        text = _numbers(text, base)
        if lexicon:
            text = _lexicon(text, base)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", text)
    text = re.sub(r"[,;:]+(?=[.!?])", "", text)
    text = re.sub(r"([!?])\s*\.(?!\.)", r"\1", text)
    text = re.sub(r"\.\s+\.", ".", text)
    text = re.sub(r"^[\s,;:]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if re.search(r"\w", text) else ""
