# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — memoria locale opzionale.

La memoria è LOCALE per impostazione predefinita e disattivabile. Nessun dato
viene inviato al cloud se non come parte della richiesta al provider scelto.
Controlli: attiva/disattiva, cancella tutto, esporta.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .providers.base import Message

STATE_DIR = Path(os.path.expanduser("~/.local/share/zeta"))
HISTORY_FILE = STATE_DIR / "history.jsonl"
PREFS_FILE = Path(os.path.expanduser("~/.config/zeta/memory.json"))
MAX_TURNS = 20     # quante coppie tenere in contesto


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
                # i comandi eseguiti restano nel file ma non nel contesto:
                # un modello piccolo li rileggeva e rispondeva imitandoli
                # («Schermata salvata…» a una domanda qualsiasi, visto davvero)
                if d.get("azione"):
                    continue
                msgs.append(Message(d["role"], d["content"]))
        except (FileNotFoundError, ValueError, KeyError):
            return []
        return msgs

    @staticmethod
    def _senza_segreti(testo: str) -> str:
        """«connettiti a Casa con password abc123» -> «... password ***»:
        una password detta a ZETA non resta scritta nella cronologia."""
        import re
        return re.sub(r"(?i)\b(password|passwd|pass|chiave|psk|pin|token|passphrase|passcode|key)\b(\s*[:=]?\s*)\S+", r"\1\2***", testo)

    def save_turn(self, user_text: str, assistant_text: str, azione: bool = False) -> None:
        if not self.enabled:
            return
        user_text = self._senza_segreti(user_text)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "a") as f:
            for role, content in (("user", user_text), ("assistant", assistant_text)):
                riga = {"t": time.time(), "role": role, "content": content}
                if azione:
                    riga["azione"] = True
                f.write(json.dumps(riga, ensure_ascii=False) + "\n")

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
