# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — optional local memory.

Memory is LOCAL by default and can be turned off. No data is sent to the
cloud except as part of the request to the chosen provider.
Controls: enable/disable, clear everything, export.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from i18n_data import load

from .providers.base import Message

STATE_DIR = Path(os.path.expanduser("~/.local/share/zeta"))
HISTORY_FILE = STATE_DIR / "history.jsonl"
PREFS_FILE = Path(os.path.expanduser("~/.config/zeta/memory.json"))
MAX_TURNS = 20     # how many user/assistant pairs to keep in context

# History sent with each question: the most recent turns that fit in an
# approximate token budget (and never more than the turn limit). A small local
# model with a long history slows down and loses track; online models have
# room for more, but every token costs time (and money).
HISTORY_BUDGET = {"local": 1500, "cloud": 6000}
HISTORY_TURNS = {"local": 6, "cloud": MAX_TURNS}


def approx_tokens(text: str) -> int:
    """About 4 characters per token (English and Italian), plus the
    per-message overhead. Approximate on purpose: no tokenizer needed."""
    return (len(text or "") + 3) // 4 + 4


def trim_history(messages: list, max_turns: int, max_tokens: int) -> list:
    """The latest messages that fit both limits, starting with a user message.

    The newest message (the question being asked) is always kept, even when
    it alone exceeds the budget: dropping it would make no sense.
    """
    kept: list = []
    used = 0
    users = 0
    for m in reversed(messages):
        cost = approx_tokens(m.content)
        if kept and used + cost > max_tokens:
            break
        if m.role == "user":
            if users >= max_turns:
                break
            users += 1
        kept.append(m)
        used += cost
    kept.reverse()
    while len(kept) > 1 and kept[0].role != "user":
        kept.pop(0)
    return kept


class Memory:
    def __init__(self):
        self.enabled = self._load_pref("enabled", True)

    def _load_pref(self, key: str, default):
        try:
            with open(PREFS_FILE) as f:
                return json.load(f).get(key, default)
        except (FileNotFoundError, ValueError):
            return default

    def set_enabled(self, value: bool) -> None:
        self.enabled = value
        PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PREFS_FILE, "w") as f:
            json.dump({"enabled": value}, f)

    def load_history(self) -> list[Message]:
        if not self.enabled:
            return []
        msgs: list[Message] = []
        try:
            with open(HISTORY_FILE) as f:
                lines = f.readlines()[-MAX_TURNS * 2:]
            for line in lines:
                d = json.loads(line)
                # executed commands stay in the file but not in the context:
                # a small model would reread them and answer by imitating them
                # ("Screenshot saved…" in reply to any question; actually seen)
                if d.get("action"):
                    continue
                msgs.append(Message(d["role"], d["content"]))
        except (FileNotFoundError, ValueError, KeyError):
            return []
        return msgs

    @staticmethod
    def _without_secrets(text: str) -> str:
        """"connect to Home with password abc123" -> "... password ***":
        a password spoken to ZETA is never left written in the history."""
        import re
        # the words that introduce a secret, in Italian and English
        return re.sub(load("memory")["secret"], r"\1\2***", text)

    def save_turn(self, user_text: str, assistant_text: str, operation: bool = False) -> None:
        if not self.enabled:
            return
        user_text = self._without_secrets(user_text)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "a") as f:
            for role, content in (("user", user_text), ("assistant", assistant_text)):
                line = {"t": time.time(), "role": role, "content": content}
                if operation:
                    line["action"] = True
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def clear(self) -> None:
        try:
            HISTORY_FILE.unlink()
        except FileNotFoundError:
            pass

    def export(self, dest: str) -> bool:
        try:
            Path(dest).write_text(HISTORY_FILE.read_text() if HISTORY_FILE.exists() else "")
            return True
        except OSError:
            return False
