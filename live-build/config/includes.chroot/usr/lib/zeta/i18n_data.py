# SPDX-License-Identifier: GPL-3.0-or-later
"""Language data: words and phrases ZETA must recognize or say in a given
language (Italian voice and text command patterns, words read aloud, user
folder names, test phrases...).

They are data, not code: they live in JSON files under
/usr/share/zeta/i18n-data/<name>.json, next to the other translations, and the
code only refers to them by key. The code stays English-only.

    from i18n_data import load
    PATTERNS = load("intents")["open_app"]["it"]

From the source tree (tests on a build machine) the folder is found relative
to this file; ZETA_I18N_DATA overrides it.
"""
import functools
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ZETA_I18N_DATA") or next(
    (d for d in ("/usr/share/zeta/i18n-data",
                 os.path.join(_HERE, "..", "..", "share", "zeta", "i18n-data"))
     if os.path.isdir(d)),
    "/usr/share/zeta/i18n-data")


@functools.lru_cache(maxsize=None)
def load(name: str):
    """The parsed content of <name>.json (cached: read once per process)."""
    with open(os.path.join(DATA_DIR, name + ".json"), encoding="utf-8") as f:
        return json.load(f)
