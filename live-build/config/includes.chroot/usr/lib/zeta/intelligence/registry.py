# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — provider manager.

Reads the configuration from ~/.config/zeta/intelligence.json. API keys are
not in that file: they have a place of their own, and they are never written
into the code or sent to any service other than the chosen provider's.

Where the keys end up
---------------------
First the system keyring is tried (Secret Service, through `secret-tool`).
ZETA RAYS, however, is minimal and does NOT install a daemon implementing that
service: on a freshly installed system `secret-tool store` fails with
«org.freedesktop.secrets was not provided by any .service files», and the key
used to be silently thrown away while Settings displayed «Key saved». Hence
the second route, which is the one normally used: systemd encrypted
credentials (`systemd-creds --user`). Each key is an encrypted file in
~/.config/zeta/keys/ (folder 0700, file 0600), encrypted with the machine's
secret key, which systemd keeps readable by root only (and by the TPM chip, if
present): only the same user, only on this computer, can decrypt it. Copied
elsewhere, or read by another user, the file is useless.
No extra daemon, no password to type.
The old plain-text file (keys.json) is converted and then deleted.
Only if systemd-creds were missing does it fall back to that file, readable
by the user only.

Which provider answers:
  1. the provider chosen by the user (Settings › AI or zeta --provider),
     even when it is not ready: ZETA then says what is wrong;
  2. otherwise («Automatic») Ollama, the local model, always.
A question is never sent to an online service the user did not choose: not
when the local model is stopped, short of memory or failing. ZETA can only
offer it in the chat, and the user's click is the choice for that question.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from i18n import language, tr

from .providers.base import Provider, ProviderConfig
from .providers.claude import ClaudeProvider
from .providers.gemini import GeminiProvider
from .providers.ollama import OllamaProvider
from .providers.openai_compat import OpenAICompatProvider

CONFIG_DIR = Path(os.path.expanduser("~/.config/zeta"))
CONFIG_FILE = CONFIG_DIR / "intelligence.json"

# available providers: id -> (class, label, kind)
CATALOG = {
    "claude":   (ClaudeProvider,       "Claude",   "cloud"),
    "gemini":   (GeminiProvider,       "Gemini",   "cloud"),
    "openai":   (OpenAICompatProvider, "OpenAI",   "cloud"),
    "deepseek": (OpenAICompatProvider, "DeepSeek", "cloud"),
    "qwen":     (OpenAICompatProvider, "Qwen",     "cloud"),
    "perplexity": (OpenAICompatProvider, "Perplexity", "cloud"),
    "mistral":  (OpenAICompatProvider, "Mistral",  "cloud"),
    "groq":     (OpenAICompatProvider, "Groq",     "cloud"),
    "xai":      (OpenAICompatProvider, "xAI Grok", "cloud"),
    "openrouter": (OpenAICompatProvider, "OpenRouter", "cloud"),
    # Any OpenAI-compatible service, on the network or on the computer (LM
    # Studio, vLLM, llama.cpp): the user enters the address and the model.
    "custom": (OpenAICompatProvider, tr("Custom (OpenAI-compatible)"), "cloud"),
    "ollama":   (OllamaProvider,       "Ollama",   "local"),
}

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


KEYS_FILE = CONFIG_DIR / "keys.json"            # old format, plain text
CREDS_DIR = CONFIG_DIR / "keys"                 # encrypted keys (systemd-creds)
_decrypted: dict = {}                            # in this process's memory


def _creds_ok() -> bool:
    """Does systemd-creds --user work here? (one probe per process)"""
    cached = getattr(_creds_ok, "_cache", None)
    if cached is not None:
        return cached
    ok = False
    try:
        p = subprocess.run(["systemd-creds", "encrypt", "--user", "--name=zeta-probe", "-", "-"],
                           input=b"probe", capture_output=True, timeout=10)
        ok = p.returncode == 0 and len(p.stdout) > 20
    except (FileNotFoundError, subprocess.SubprocessError):
        ok = False
    _creds_ok._cache = ok
    return ok


def _cred_file(name: str) -> Path:
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_") or "key"
    return CREDS_DIR / (safe_name + ".cred")


def _cred_get(name: str) -> str:
    if name in _decrypted:
        return _decrypted[name]
    f = _cred_file(name)
    if not f.exists():
        return ""
    try:
        p = subprocess.run(["systemd-creds", "decrypt", "--user", "--name=zeta-" + name, str(f), "-"],
                           capture_output=True, timeout=10)
        v = p.stdout.decode("utf-8", "replace").strip() if p.returncode == 0 else ""
    except (FileNotFoundError, subprocess.SubprocessError):
        v = ""
    _decrypted[name] = v
    return v


def _cred_set(name: str, value: str) -> bool:
    _decrypted.pop(name, None)
    f = _cred_file(name)
    if not value:
        try:
            f.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True
    try:
        CREDS_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(CONFIG_DIR, 0o700)
        os.chmod(CREDS_DIR, 0o700)
        p = subprocess.run(["systemd-creds", "encrypt", "--user", "--name=zeta-" + name, "-", "-"],
                           input=value.encode(), capture_output=True, timeout=10)
        if p.returncode != 0 or not p.stdout:
            return False
        tmp = f.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(p.stdout)
        os.replace(tmp, f)
    except (OSError, subprocess.SubprocessError):
        return False
    # check that it really reads back before reporting «saved»
    return _cred_get(name) == value


def _migrate_plaintext_file() -> None:
    """keys.json (plain text, older versions) -> encrypted files, then removed."""
    if getattr(_migrate_plaintext_file, "_done", False):
        return
    _migrate_plaintext_file._done = True
    if not KEYS_FILE.exists() or not _creds_ok():
        return
    old_entries = _file_keys()
    for name, value in old_entries.items():
        value = str(value).strip()
        if value and not _cred_set(name, value):
            return                      # something is wrong: the file stays, nothing is lost
    try:
        size = KEYS_FILE.stat().st_size
        with open(KEYS_FILE, "r+b") as fh:          # overwritten before deleting
            fh.write(b"\0" * size)
            fh.flush()
            os.fsync(fh.fileno())
        KEYS_FILE.unlink()
    except OSError:
        pass


def _secret_service() -> bool:
    """True only if the system really has a keyring that answers.

    Having `secret-tool` installed is not enough: it is only the client.
    A daemon providing org.freedesktop.secrets is needed. The answer is
    cached: the question is asked once per process, not for every key.
    """
    cached = getattr(_secret_service, "_cache", None)
    if cached is not None:
        return cached
    ok = False
    try:
        out = subprocess.run(["secret-tool", "search", "--unlock", "zeta-provider", "_probe"],
                             capture_output=True, text=True, timeout=5)
        # 0 = found, 1 = not found but the service exists; a missing service
        # is recognized from the message, not from the exit code.
        ok = "not provided by any .service" not in (out.stderr or "")
    except (FileNotFoundError, subprocess.SubprocessError):
        ok = False
    _secret_service._cache = ok
    return ok


def _file_keys() -> dict:
    try:
        with open(KEYS_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _file_keys_write(d: dict) -> bool:
    """Writes the keys file readable by the user only.

    Permissions are set BEFORE writing the content: creating the file and
    restricting it afterwards leaves a window, however short, in which the key
    is readable by anyone on the computer.
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(CONFIG_DIR, 0o700)
        tmp = KEYS_FILE.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, KEYS_FILE)
        os.chmod(KEYS_FILE, 0o600)
        return True
    except OSError:
        return False


def _keyring_get(name: str) -> str:
    """A provider's API key. Empty string if there is none."""
    if _secret_service():
        try:
            out = subprocess.run(["secret-tool", "lookup", "zeta-provider", name],
                                 capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
    _migrate_plaintext_file()
    if _creds_ok():
        return _cred_get(name)
    return str(_file_keys().get(name, "")).strip()


def keyring_set(name: str, value: str) -> bool:
    """Saves (or deletes, with an empty value) a provider's key.

    Returns True ONLY if the key really ended up somewhere: the caller must
    tell the user. This value used to be ignored, and Settings displayed
    «Key saved» even when it was not true.
    """
    value = (value or "").strip()
    if _secret_service():
        try:
            if value:
                p = subprocess.run(["secret-tool", "store", "--label=ZETA RAYS %s" % name,
                                    "zeta-provider", name], input=value, text=True, timeout=5)
            else:
                p = subprocess.run(["secret-tool", "clear", "zeta-provider", name],
                                   capture_output=True, timeout=5)
            if p.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
    _migrate_plaintext_file()
    if _creds_ok():
        return _cred_set(name, value)
    d = _file_keys()
    if value:
        d[name] = value
    else:
        d.pop(name, None)
    return _file_keys_write(d)


def keyring_where() -> str:
    """Where the keys are kept, to show in Settings."""
    if _secret_service():
        return tr("system keyring")
    if _creds_ok():
        # zeta-selftest and Settings only keep the part before " ("
        return tr("encrypted in {path} (only you, only on this computer)").format(path=CREDS_DIR)
    return str(KEYS_FILE)


def load_settings() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
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

    def _config(self, provider_id: str) -> ProviderConfig:
        cls, label, kind = CATALOG[provider_id]
        opts = self.settings.get("providers", {}).get(provider_id, {})
        return ProviderConfig(
            name=provider_id, label=label, kind=kind,
            model=opts.get("model", ""),
            endpoint=opts.get("endpoint", ""),
            api_key="" if kind == "local" else _keyring_get(provider_id),
            temperature=float(opts.get("temperature", 0.7)),
            # the local model answers briefly on purpose (fast even on slow
            # computers): it stays that way unless the user chooses otherwise
            max_tokens=int(opts.get("max_tokens",
                                    OllamaProvider.MAX_TOKEN if kind == "local" else 4096)),
            timeout=float(opts.get("timeout", 0) or 0),
            stream=bool(opts.get("stream", True)),
            context=int(opts.get("context", 0) or 0),
            system=self.system,
        )

    def get(self, provider_id: str) -> Provider:
        cls = CATALOG[provider_id][0]
        return cls(self._config(provider_id))

    def choose(self, provider_id: str) -> None:
        """Sets which AI to use. «auto» goes back to automatic choice."""
        s = dict(self.settings)
        if provider_id in (None, "", "auto"):
            s.pop("default", None)
        elif provider_id in CATALOG:
            s["default"] = provider_id
        else:
            raise ValueError(tr("unknown provider: {name}").format(name=provider_id))
        save_settings(s)
        self.settings = s

    def set_option(self, provider_id: str, key: str, value) -> None:
        """Saves a provider option (model, endpoint...)."""
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

    def test(self, provider_id: str) -> tuple[bool, str]:
        """Tests a provider's connection and returns (success, message)."""
        if provider_id not in CATALOG:
            return False, tr("Unknown provider.")
        try:
            return self.get(provider_id).test()
        except Exception as e:  # noqa: BLE001 - a test must never bring the app down
            return False, tr("Unexpected error: {error}").format(error=e)

    def resolve_default(self) -> Provider:
        """Chooses the provider to use (see the order at the top of the file).

        A provider the user chose is used even when it is not ready: ZETA then
        says what is wrong. Switching silently to another one would send the
        questions somewhere the user did not choose (a cloud service instead
        of the local model) or hide the problem. «Automatic» means the local
        model, never an online service (security audit, 2.1): when Ollama is
        stopped or short of memory ZETA explains it and can offer, in the
        chat, a service that has a key (see cloud_offer).
        """
        chosen = self.settings.get("default")
        if chosen and chosen in CATALOG:
            return self.get(chosen)
        return self.get("ollama")

    def cloud_offer(self) -> str:
        """An online service with a key that ZETA may OFFER (never use by
        itself) when the local model can't answer; "" if there is none."""
        for pid, (_cls, _label, kind) in CATALOG.items():
            if kind == "cloud" and pid != "custom" and self.get(pid).available():
                return pid
        return ""

    def status(self) -> list[dict]:
        """Status of every provider, for Settings and diagnostics."""
        rows = []
        for pid, (_cls, label, kind) in CATALOG.items():
            prov = self.get(pid)
            row = {"id": pid, "label": label, "kind": kind,
                   "ready": prov.available(), "model": prov.config.model,
                   "endpoint": prov.config.endpoint,
                   "model_default": default_model(pid)}
            if pid == "ollama":
                row["local_models"] = prov.list_models()
            rows.append(row)
        return rows


def default_model(provider_id: str) -> str:
    """The model used when the user does not choose one."""
    from .providers import claude, gemini, ollama, openai_compat
    if provider_id == "claude":
        return claude.DEFAULT_MODEL
    if provider_id == "gemini":
        return gemini.DEFAULT_MODEL
    if provider_id == "ollama":
        return ollama.DEFAULT_MODEL
    return openai_compat.PRESETS.get(provider_id, ("", "", ""))[2]


def capabilities(provider_id: str) -> dict:
    """What ZETA's code really does with each provider (not what the service
    could do in general): ZETA's actions (tool calling), streamed replies
    (only without actions: the first round of a request with actions must
    arrive whole), its own web search. Images are not sent to any provider."""
    from .providers.openai_compat import WITHOUT_TOOLS
    cls = CATALOG[provider_id][0]
    if provider_id in ("ollama", "gemini"):
        tools = False
    elif cls is OpenAICompatProvider:
        tools = provider_id not in WITHOUT_TOOLS
    else:
        tools = bool(getattr(cls, "uses_tools", True))
    return {"streaming": not tools, "tools": tools, "web": provider_id == "perplexity"}
