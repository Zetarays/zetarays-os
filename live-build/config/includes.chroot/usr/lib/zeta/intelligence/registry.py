# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — settings and the local model.

Since 2.5 ZETA answers ONLY with models that run on this computer: Ollama,
listening on 127.0.0.1, with the models installed in the system. There is no
online AI service, no API key, no fallback to the cloud: conversations,
memories, voice and files never leave the computer. When the local model
cannot answer (stopped, not enough memory) ZETA says why, and may use a
smaller installed local model instead (models.fallback).

The settings live in ~/.config/zeta/intelligence.json. Keys left there by
2.1 and earlier ("default", the options of the online services) are ignored.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from i18n import language, tr

from . import models
from .providers.base import Provider, ProviderConfig
from .providers.ollama import OllamaProvider

CONFIG_DIR = Path(os.path.expanduser("~/.config/zeta"))
CONFIG_FILE = CONFIG_DIR / "intelligence.json"

# The only provider. Kept as a table: Settings, the command line and the
# diagnostics list what is in it.
LOCAL = "ollama"
CATALOG = {LOCAL: (OllamaProvider, "Ollama", "local")}

# Short, positively worded instructions: given a list of prohibitions, the
# local model (1B) refused even harmless requests («write a sentence about
# Rome»: observed). Tested on 8 normal requests: 0 refusals, versus 1-2
# before. In English (small models follow them better), with the reply
# language left to whoever writes; the system language is used when the
# request has no clear language.
_LANGUAGE_NAMES = {"it": "Italian", "en": "English", "de": "German", "fr": "French",
                   "es": "Spanish", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish"}


# Settings › AI › "Reply language": "auto" (the language the user writes in,
# the system language when unclear) or "system" (always the language chosen in
# Language & Region, whatever language the user writes in).
REPLY_LANGUAGE = "reply_language"
LANGUAGES_FILE = "/usr/share/zeta/languages.json"


def language_name(code: str) -> str:
    """English name of a system language ("de" -> "German"), from the list of
    the 35 languages offered in Language & Region."""
    if code in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[code]
    try:
        with open(LANGUAGES_FILE, encoding="utf-8") as f:
            for entry in json.load(f):
                if entry.get("locale", "").split("_")[0] == code:
                    return entry.get("name", code).split(" (")[0]
    except (OSError, ValueError):
        pass
    return code


def language_label(code: str) -> str:
    """Name of a system language as shown in Language & Region (its own
    name, e.g. "Deutsch", "Italiano")."""
    try:
        with open(LANGUAGES_FILE, encoding="utf-8") as f:
            for entry in json.load(f):
                if entry.get("locale", "").split("_")[0] == code:
                    return entry.get("name", code)
    except (OSError, ValueError):
        pass
    return language_name(code)


def _default_prompt() -> str:
    lang = language()
    name = language_name(lang)
    return (
        "You are ZETA, the assistant of ZETA RAYS OS, private by design. Always reply in the "
        "language the user writes in (if unclear, use %s), briefly, clearly and kindly: no "
        "filler, no repeating the question. Be glad to help: write texts and poems, explain, "
        "answer questions, give advice. When you are not sure, say so instead of guessing. "
        "Refuse only requests that are clearly illegal or harm other people; security work on "
        "your own or authorized systems is legitimate. Never say you performed an action on the "
        "computer: the system performs actions and reports the real outcome. The operating "
        "system is called ZETA RAYS OS."
        % name
    )


DEFAULT_SYSTEM = _default_prompt()


def current_system_prompt(settings: dict | None = None) -> str:
    """The system prompt of every request (persona and fixed rules). The
    model warm-up (OllamaProvider.preload) sends exactly the same text, so
    the first question only costs its own tokens."""
    from . import context
    settings = load_settings() if settings is None else settings
    base = settings.get("system") or DEFAULT_SYSTEM
    return context.system_prompt(base, always_language=always_language(settings))


def always_language(settings: dict) -> str:
    """English name of the language every reply must use, or "" when the
    reply follows the language of the question (Settings › AI)."""
    return language_name(language()) if settings.get(REPLY_LANGUAGE) == "system" else ""


def load_settings() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    tmp.replace(CONFIG_FILE)


class Registry:
    def __init__(self):
        self.settings = load_settings()
        self.system = self.settings.get("system", DEFAULT_SYSTEM)

    def _options(self) -> dict:
        return self.settings.get("providers", {}).get(LOCAL, {})

    def _config(self) -> ProviderConfig:
        opts = self._options()
        return ProviderConfig(
            name=LOCAL, label="Ollama", kind="local",
            model=opts.get("model", ""),
            endpoint=opts.get("endpoint", ""),
            temperature=float(opts.get("temperature", 0.7)),
            # the local model answers briefly on purpose (fast even on slow
            # computers): it stays that way unless the user chooses otherwise
            max_tokens=int(opts.get("max_tokens", OllamaProvider.MAX_TOKEN)),
            timeout=float(opts.get("timeout", 0) or 0),
            stream=bool(opts.get("stream", True)),
            # the machine's profile decides the context unless the user did
            context=int(opts.get("context", 0) or models.context_size()),
            system=self.system,
        )

    def get(self, provider_id: str = LOCAL) -> Provider:
        if provider_id not in CATALOG:
            raise ValueError(tr("unknown provider: {name}").format(name=provider_id))
        return OllamaProvider(self._config())

    def set_option(self, provider_id: str, key: str, value) -> None:
        """Saves an option of the local model (model, temperature...)."""
        s = dict(self.settings)
        prov = dict(s.get("providers", {}))
        conf = dict(prov.get(provider_id, {}))
        if value in (None, ""):
            conf.pop(key, None)
        else:
            conf[key] = value
        prov[provider_id] = conf
        s["providers"] = prov
        save_settings(s)
        self.settings = s

    def test(self, provider_id: str = LOCAL) -> tuple[bool, str]:
        """Tests the local model and returns (success, message)."""
        try:
            return self.get(provider_id).test()
        except Exception as e:  # noqa: BLE001 - a test must never bring the app down
            return False, tr("Unexpected error: {error}").format(error=e)

    def resolve_default(self) -> Provider:
        """The provider that answers: always the local model."""
        return self.get(LOCAL)

    def status(self) -> list[dict]:
        """Status of the local model, for Settings and diagnostics."""
        prov = self.get(LOCAL)
        m = models.machine()
        return [{"id": LOCAL, "label": "Ollama", "kind": "local", "ready": prov.available(),
                 "model": prov._model(), "endpoint": prov._base(),
                 "model_default": models.preferred()[0], "profile": m.profile,
                 "local_models": prov.list_models()}]
