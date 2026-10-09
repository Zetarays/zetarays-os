# SPDX-License-Identifier: GPL-3.0-or-later
"""Languages for text recognition (Tesseract): the system language first,
then English, only among those installed (tesseract-ocr-*)."""
import glob
import os

# language code of the locale -> Tesseract model
TESSERACT = {"it": "ita", "fr": "fra", "de": "deu", "es": "spa", "pt": "por", "nl": "nld",
             "pl": "pol", "ru": "rus", "uk": "ukr", "cs": "ces", "sk": "slk", "hu": "hun",
             "ro": "ron", "bg": "bul", "el": "ell", "tr": "tur", "sv": "swe", "nb": "nor",
             "da": "dan", "fi": "fin", "hr": "hrv", "sl": "slv", "sr": "srp", "he": "heb",
             "ar": "ara", "fa": "fas", "hi": "hin", "bn": "ben", "ja": "jpn", "ko": "kor",
             "zh_CN": "chi_sim", "zh_TW": "chi_tra", "en": "eng"}


def installate():
    trovate = set()
    for f in glob.glob("/usr/share/tesseract-ocr/*/tessdata/*.traineddata"):
        trovate.add(os.path.basename(f)[:-len(".traineddata")])
    return trovate


def lingue():
    """e.g. "fra+eng" on a French system; "eng" when nothing else is there."""
    loc = ""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        loc = os.environ.get(var, "")
        if loc:
            break
    loc = loc.split(".")[0]
    codice = TESSERACT.get(loc) or TESSERACT.get(loc.split("_")[0], "")
    ok = installate()
    scelte = [c for c in (codice, "eng") if c and c in ok]
    return "+".join(dict.fromkeys(scelte)) or "eng"
