# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — what ZETA remembers, and what it sends back.

Everything is stored on this computer, in the local store (store.py: one
SQLite file readable by the user only). Controls: Settings › AI › Memory
(on/off, how long the conversation is kept, the list of long-term memories
with delete, export, clear) and `zeta --forget`.

Three kinds of memory, kept apart on purpose:
  - the conversation: the latest turns go back to the model with each
    question (a bounded window, see history_budget); older turns stay in the
    store for the retention period, then are deleted;
  - long-term memories: only what the user asked ZETA to remember; each
    question gets the two or three that match it, never the whole list;
  - reference knowledge: verified facts and web sources, with provenance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from i18n_data import load

from . import store
from .providers.base import Message

PREFS_FILE = Path(os.path.expanduser("~/.config/zeta/memory.json"))
MAX_TURNS = 20     # how many user/assistant pairs to keep in context

# History sent with each question: the most recent turns that fit in an
# approximate token budget (and never more than the turn limit). A small local
# model with a long history slows down and loses track.
HISTORY_BUDGET = 1500
HISTORY_TURNS = 6

# A local model rereads the whole history only now and then (after loading,
# or when the window is cut): that reread must stay short on a slow processor.
# The budget follows the speed measured on this computer (resources.py):
# about REREAD_SECONDS of reading, between LOCAL_MIN and HISTORY_BUDGET.
REREAD_SECONDS = 12
LOCAL_MIN = 400
LOCAL_UNKNOWN = 900            # before the first measurement


def history_budget() -> int:
    """Token budget of the history sent to the local model."""
    from .resources import prompt_speed
    rate = prompt_speed()
    if rate <= 0:
        return LOCAL_UNKNOWN
    return int(max(LOCAL_MIN, min(HISTORY_BUDGET, rate * REREAD_SECONDS)))


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
        prefs = self._prefs()
        self.enabled = bool(prefs.get("enabled", True))
        self.long_term = bool(prefs.get("long_term", True))
        days = prefs.get("retention_days", store.RETENTION_DAYS)
        self.retention_days = days if days in store.RETENTION_CHOICES else store.RETENTION_DAYS
        self._pruned = False

    @staticmethod
    def _prefs() -> dict:
        try:
            with open(PREFS_FILE) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_pref(self, key: str, value) -> None:
        data = self._prefs()
        data[key] = value
        PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PREFS_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f)
        tmp.replace(PREFS_FILE)

    def set_enabled(self, value: bool) -> None:
        self.enabled = value
        self._save_pref("enabled", value)

    def set_long_term(self, value: bool) -> None:
        self.long_term = value
        self._save_pref("long_term", value)

    def set_retention(self, days: int) -> None:
        if days not in store.RETENTION_CHOICES:
            raise ValueError(days)
        self.retention_days = days
        self._save_pref("retention_days", days)
        store.prune(days)

    def load_history(self) -> list[Message]:
        if not self.enabled:
            return []
        try:
            if not self._pruned:
                store.prune(self.retention_days)
                self._pruned = True
            rows = store.recent_turns(MAX_TURNS)
        except Exception:  # noqa: BLE001 - memory must never stop ZETA from answering
            return []
        # executed commands stay in the store but not in the context: a small
        # model would reread them and answer by imitating them ("Screenshot
        # saved…" in reply to any question; actually seen)
        return [Message(role, content) for role, content, action in rows if not action]

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
        try:
            store.save_turn(self._without_secrets(user_text), assistant_text, operation)
        except Exception:  # noqa: BLE001 - an answer is not lost because the disk is full
            pass

    # --- long-term memories ------------------------------------------------
    def remember(self, text: str) -> tuple[str, str]:
        """Store what the user asked to remember: (outcome, stored text)."""
        fact, outcome = store.add_fact(self._without_secrets(text))
        return outcome, fact.text if fact else ""

    def forget(self, text: str) -> list[str]:
        return store.forget_matching(text)

    def recall(self, question: str, limit: int = 3) -> list[str]:
        """The long-term memories that match a question (empty when off)."""
        if not (self.enabled and self.long_term):
            return []
        try:
            return [f.text for f in store.search_facts(question, limit)]
        except Exception:  # noqa: BLE001
            return []

    def facts(self) -> list:
        return store.list_facts()

    def clear(self, what: str = "conversation") -> None:
        store.clear(what)

    def export(self, dest: str) -> bool:
        return store.export(dest)
