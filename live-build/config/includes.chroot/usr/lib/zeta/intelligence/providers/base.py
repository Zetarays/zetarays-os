# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — common interface for AI providers.

Every provider (Claude, Gemini, OpenAI, DeepSeek, Qwen, Ollama) exposes the
same interface, so ZETA does not need to know the details of each one.
No external dependencies: only urllib from the standard library.
"""
from __future__ import annotations

import errno
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterator

from i18n import tr


class ProviderError(Exception):
    """A provider error, carrying a message that is already user-readable."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass
class Message:
    role: str            # "user" | "assistant"
    content: str


@dataclass
class ToolSpec:
    """Description of a tool (action) the AI can request."""
    name: str
    description: str
    schema: dict         # JSON schema of the parameters


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    """A provider's reply to one conversation turn."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"    # end_turn | tool_use | refusal | max_tokens


@dataclass
class ProviderConfig:
    name: str                        # internal id (claude, gemini, ...)
    label: str                       # name shown to the user
    kind: str                        # "cloud" | "local"
    model: str = ""
    endpoint: str = ""
    api_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    system: str = ""
    timeout: float = 0.0             # seconds; 0 = default (120 s, 300 s when streaming)
    stream: bool = True              # reply appears while it is being written
    context: int = 0                 # context window (local models only); 0 = model default


class Provider:
    """Base of every provider. `chat` runs one turn; `stream` runs one streamed."""

    # Can the provider use ZETA's actions (tool calling)? Those that do not
    # can answer straight away in streaming mode: the reply appears while it
    # is being written, instead of all at once at the end.
    uses_tools = True

    def __init__(self, config: ProviderConfig):
        self.config = config
        # Maximum wait time, when it needs to be shorter than usual: the
        # connection test cannot freeze a window for two minutes if the
        # network does not respond.
        self.timeout: float | None = None

    # --- Public API ---
    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> Reply:
        raise NotImplementedError

    def stream(self, messages: list[Message],
               on_text: Callable[[str], None]) -> Reply:
        """Text-only streaming. Providers without streaming fall back to chat."""
        reply = self.chat(messages)
        if reply.text:
            on_text(reply.text)
        return reply

    def offered_models(self) -> list[str]:
        """The models the service actually offers (for automatic fallback).
        Every provider able to tell overrides this; [] = unknown."""
        return []

    def available(self) -> bool:
        """True if the provider is configured and usable."""
        if self.config.kind == "cloud":
            return bool(self.config.api_key)
        return True

    def test(self, timeout: float = 25.0) -> tuple[bool, str]:
        """Actually test the connection and report the outcome, in the user's language.

        Checking for a key is not enough: an expired key, a model that no
        longer exists or a network with no outbound access all look the same
        ("configured") until you try. Here the smallest possible request is
        made and the real outcome is reported.
        """
        if self.config.kind == "cloud" and not self.config.api_key:
            return False, tr("The API key is missing.")
        prev_tokens, prev_timeout = self.config.max_tokens, self.timeout
        self.config.max_tokens, self.timeout = 16, timeout
        try:
            self.chat([Message(role="user", content="ok")])
            return True, tr("Connected (model {model}).").format(
                model=self.config.model or tr("default"))
        except ProviderError as e:
            return False, str(e)
        except NotImplementedError:
            return False, tr("This provider can't be used yet.")
        except Exception as e:  # noqa: BLE001 - the test must never bring down the UI
            return False, tr("Unexpected error: {error}").format(error=e)
        finally:
            self.config.max_tokens, self.timeout = prev_tokens, prev_timeout

    # --- Common helpers ---
    def _unreachable(self, reason) -> "ProviderError":
        """Network failure reasons in the user's language (previously the raw
        "timed out", "Name or service not known"... came through)."""
        # Check the error type and code first: the system text may be
        # translated (in GTK apps libc speaks the user's language).
        m = str(reason).lower()
        num = getattr(reason, "errno", None)
        if isinstance(reason, TimeoutError) or "timed out" in m or "timeout" in m:
            explanation = tr("it didn't respond in time")
        elif (isinstance(reason, socket.gaierror) or "name or service" in m
              or "temporary failure in name resolution" in m or "nodename" in m):
            explanation = tr("no internet connection, or DNS isn't responding")
        elif isinstance(reason, ConnectionRefusedError) or num == errno.ECONNREFUSED or "refused" in m:
            explanation = tr("connection refused")
        elif num in (errno.ENETUNREACH, errno.EHOSTUNREACH) or "unreachable" in m:
            explanation = tr("network unreachable")
        else:
            explanation = str(reason)
        return ProviderError(tr("Can't reach {name}: {reason}.").format(
            name=self.config.label, reason=explanation), retryable=True)

    def _post(self, url: str, payload: dict, headers: dict,
              timeout: float = 120.0) -> dict:
        timeout = self.timeout or self.config.timeout or timeout
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            msg = self._error_message(e.code, body)
            raise ProviderError(msg, retryable=e.code in (429, 500, 502, 503, 529),
                                status=e.code) from None
        except urllib.error.URLError as e:
            raise self._unreachable(e.reason) from None
        except (TimeoutError, OSError) as e:
            # the service stopped responding midway (read timed out)
            raise self._unreachable(e) from None

    def _post_stream(self, url: str, payload: dict, headers: dict,
                     timeout: float = 300.0) -> Iterator[bytes]:
        timeout = self.timeout or self.config.timeout or timeout
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise ProviderError(self._error_message(e.code, body),
                                retryable=e.code in (429, 500, 502, 503, 529),
                                status=e.code) from None
        except urllib.error.URLError as e:
            raise self._unreachable(e.reason) from None
        except (TimeoutError, OSError) as e:
            # the service stopped responding midway (read timed out)
            raise self._unreachable(e) from None
        try:
            for raw in resp:
                yield raw
        except (TimeoutError, OSError) as e:
            raise self._unreachable(e) from None

    def _error_message(self, code: int, body: str) -> str:
        detail = ""
        try:
            j = json.loads(body)
            detail = (j.get("error", {}) or {}).get("message", "") if isinstance(j.get("error"), dict) else str(j.get("error", ""))
        except (ValueError, AttributeError):
            detail = body[:200]
        if code == 401 or (code == 400 and "api key" in detail.lower()):
            # Gemini replies 400 "API key not valid" instead of 401
            return tr("{name}: invalid or missing API key.").format(name=self.config.label)
        if code == 403:
            return tr("{name}: access denied for this API key.").format(name=self.config.label)
        if code == 404:
            # "model" / "modello" and "not found" are what assistant.py looks
            # for to recognize a model that no longer exists
            return tr("{name}: model or endpoint not found ({model}).").format(
                name=self.config.label, model=self.config.model)
        if code == 429:
            return tr("{name}: too many requests, try again shortly.").format(name=self.config.label)
        if code >= 500:
            return tr("{name}: service error, try again later.").format(name=self.config.label)
        return "%s: %s" % (self.config.label,
                           detail or tr("error {code}").format(code=code))


# Preferred models when the default one no longer exists (names change over
# time): fast ones first. They are matched as substrings of the name.
FAVORITES = {
    "claude": ["claude-haiku-5", "claude-sonnet-5", "haiku", "sonnet"],
    "gemini": ["gemini-3.8-flash", "gemini-3.5-flash", "flash", "gemini"],
    "openai": ["gpt-6-luna", "gpt-5.6-terra", "gpt-6", "gpt-5", "gpt-4.1-mini"],
    "deepseek": ["deepseek-flash", "deepseek-v4-flash", "deepseek-chat"],
    "qwen": ["qwen3.8-flash", "flash", "qwen-plus", "plus", "qwen-turbo", "qwen-max"],
    "perplexity": ["sonar"],
    "mistral": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest", "mistral"],
    "groq": ["gpt-oss-20b", "gpt-oss", "llama", "qwen"],
    "xai": ["grok-4", "grok"],
    "openrouter": ["openrouter/auto"],
}
_NON_CHAT = ("embed", "image", "tts", "audio", "whisper", "moderation", "guard", "realtime",
             "transcribe", "vision-preview", "search-preview", "dall-e", "veo", "imagen", "live")


def choose_model(provider_id: str, offered: list[str]) -> str:
    """The chat model to use among those offered, according to FAVORITES."""
    chat = [m for m in offered if m and not any(x in m.lower() for x in _NON_CHAT)]
    for part in FAVORITES.get(provider_id, []):
        found = sorted((m for m in chat if part in m.lower()), reverse=True)
        # on a tie, prefer the undated name (an alias that tracks updates)
        found.sort(key=lambda m: (not m.lower().startswith(part), len(m)))
        if found:
            return found[0]
    return chat[0] if chat else ""
