# SPDX-License-Identifier: GPL-3.0-or-later
"""Test sentences for tools/voice-bench: what ZETA typically says (confirmations,
numbers, dates, times, apostrophes, English words, a question, an exclamation,
a long sentence with commas).

The sentences are language data: data/sentences.json, {"it": [...], "en": [...]}.
"""
import json
import os

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sentences.json"),
          encoding="utf-8") as _f:
    SENTENCES = json.load(_f)
