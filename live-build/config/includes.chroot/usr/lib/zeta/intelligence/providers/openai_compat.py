# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenAI-API-compatible providers (chat/completions) for ZETA RAYS Intelligence.

A single code path covers OpenAI, DeepSeek, Qwen, Perplexity, Mistral, Groq,
xAI, OpenRouter and any compatible service (local ones too: LM Studio, vLLM,
llama.cpp server): only the endpoint, model and key change. No SDK: calls go
through urllib.

Model names change often: the ones here are just a starting point and can be
changed in Settings › AI. If a model no longer exists, the connection test
lists the models the service actually offers.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Iterator

import urllib.parse
import urllib.request

from i18n import tr

from .base import Message, Provider, ProviderError, Reply, ToolCall, ToolSpec

# Default models checked against each service's documentation on October 7,
# 2026: the fast and cheap ones, suited to an assistant. If one disappears,
# ZETA picks another one among those offered by itself (assistant.py).
PRESETS = {
    "openai":     ("OpenAI",     "https://api.openai.com/v1/chat/completions",   "gpt-6-luna"),
    "deepseek":   ("DeepSeek",   "https://api.deepseek.com/v1/chat/completions", "deepseek-flash"),
    "qwen":       ("Qwen",       "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen3.8-flash"),
    # Perplexity: answers by searching the web, with sources
    "perplexity": ("Perplexity", "https://api.perplexity.ai/chat/completions",   "sonar"),
    "mistral":    ("Mistral",    "https://api.mistral.ai/v1/chat/completions",   "mistral-small-latest"),
    "groq":       ("Groq",       "https://api.groq.com/openai/v1/chat/completions", "openai/gpt-oss-20b"),
    # xAI: the chat/completions interface is the compatible one ("legacy" for xAI)
    "xai":        ("xAI Grok",   "https://api.x.ai/v1/chat/completions",         "grok-4.7"),
    # OpenRouter: a single key for many models; "auto" picks one by itself
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1/chat/completions", "openrouter/auto"),
    # any compatible service: the user enters the address and model
    "custom": ("Custom", "", ""),
}

# Services that are NOT sent ZETA's actions (function calling): requests to
# them go without, and the reply arrives as a stream.
#  - perplexity: does not accept them;
#  - custom: usually a small local model. Tested with llama3.2:1b:
#    with the 52 actions attached it answered "dimmi ciao" ("say hi") with a
#    raw function call, after 11 s instead of 0.2 s. ZETA already recognizes
#    commands by itself (intents.py), before the model.
WITHOUT_TOOLS = {"perplexity", "custom"}

# OpenAI's reasoning models (gpt-5 and later, o series) reject max_tokens
# (they want max_completion_tokens) and any temperature other than the
# default: with these two fields ZETA only got a 400 error.
_OPENAI_REASONING = re.compile(r"^(gpt-[5-9]|o[1-9])")


def _effort(model: str) -> str:
    """Minimal reasoning effort: an assistant must answer right away.
    The first gpt-5 models know "minimal"; from gpt-5.1 on there is "none",
    and on Chat Completions gpt-6 uses actions only with "none". o series:
    their own default."""
    base_model = model.split("-20", 1)[0]                # without the version date
    if base_model in ("gpt-5", "gpt-5-mini", "gpt-5-nano"):
        return "minimal"
    return "none" if base_model.startswith("gpt-") else ""

# Services that can run on the computer itself, without a key
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class OpenAICompatProvider(Provider):
    # A service that rejects actions is detected on its first reply: from
    # then on, requests to that service go without them (for this session).
    _rejects_tools: set[str] = set()
    # Fields a service has rejected (per service and model): learned from the
    # first 400 reply, they are not sent again during the session.
    _adaptations: dict[tuple[str, str], set[str]] = {}

    @property
    def uses_tools(self) -> bool:          # type: ignore[override]
        n = self.config.name
        return n not in WITHOUT_TOOLS and n not in self._rejects_tools

    def _is_local(self) -> bool:
        host = urllib.parse.urlparse(self._url()).hostname or ""
        return host in _LOCAL_HOSTS or host.endswith(".local")

    def available(self) -> bool:
        if not self._url() or not self._model():
            return False
        return bool(self.config.api_key) or self._is_local()

    def _url(self) -> str:
        return self.config.endpoint or PRESETS.get(self.config.name, ("", "", ""))[1]

    def _model(self) -> str:
        return self.config.model or PRESETS.get(self.config.name, ("", "", ""))[2]

    def _headers(self) -> dict:
        h = {"content-type": "application/json"}
        if self.config.api_key:           # local services often do not want it
            h["authorization"] = "Bearer %s" % self.config.api_key
        return h

    def _messages(self, messages: list[Message]) -> list[dict]:
        out = []
        if self.config.system:
            out.append({"role": "system", "content": self.config.system})
        out.extend({"role": m.role, "content": m.content} for m in messages)
        return out

    def _base(self, messages: list[Message]) -> dict:
        """The request shared by chat and stream, in the form the service and
        model accept."""
        model = self._model()
        payload = {"model": model, "messages": self._messages(messages),
                   "max_tokens": self.config.max_tokens,
                   "temperature": self.config.temperature}
        if self.config.name == "openai" and _OPENAI_REASONING.match(model):
            payload["max_completion_tokens"] = payload.pop("max_tokens")
            payload.pop("temperature")
            if _effort(model):
                payload["reasoning_effort"] = _effort(model)
        for field in self._adaptations.get((self.config.name, model), ()):
            self._remove(payload, field)
        return payload

    @staticmethod
    def _remove(payload: dict, field: str) -> None:
        if field == "max_tokens" and "max_tokens" in payload:
            payload["max_completion_tokens"] = payload.pop("max_tokens")
        else:
            payload.pop(field, None)

    def _adapt(self, payload: dict, e: ProviderError) -> bool:
        """A 400 that names a request field ("Unsupported parameter:
        'max_tokens'", "temperature does not support 0.7"): remove it and
        retry. True if the request changed."""
        if e.status not in (400, 422):
            return False
        msg = str(e).lower()
        for field in ("max_tokens", "temperature", "reasoning_effort"):
            if field in payload and field in msg:
                self._remove(payload, field)
                self._adaptations.setdefault((self.config.name, payload["model"]), set()).add(field)
                return True
        return False

    def _tools(self, tools: list[ToolSpec] | None) -> list[dict] | None:
        if not tools:
            return None
        return [{"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.schema}} for t in tools]

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> Reply:
        payload = self._base(messages)
        tool_defs = self._tools(tools) if self.uses_tools else None
        if tool_defs:
            payload["tools"] = tool_defs
        for _attempt in range(4):
            try:
                data = self._post(self._url(), payload, self._headers())
                break
            except ProviderError as e:
                if self._adapt(payload, e):
                    continue
                # Many compatible services do not accept actions and answer
                # 400/422: retry without them instead of failing.
                if "tools" not in payload or e.status not in (400, 404, 422):
                    raise
                self._rejects_tools.add(self.config.name)
                payload.pop("tools", None)
        else:
            data = self._post(self._url(), payload, self._headers())
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        reply = Reply(text=msg.get("content") or "")
        reply.stop_reason = "tool_use" if msg.get("tool_calls") else "end_turn"
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            reply.tool_calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""),
                                             arguments=args))
        usage = data.get("usage", {})
        reply.input_tokens = usage.get("prompt_tokens", 0)
        reply.output_tokens = usage.get("completion_tokens", 0)
        return reply

    def stream(self, messages: list[Message],
               on_text: Callable[[str], None]) -> Reply:
        payload = self._base(messages)
        payload["stream"] = True
        reply = Reply()
        for raw in self._stream_lines(payload):
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                ev = json.loads(body)
            except ValueError:
                continue
            delta = (ev.get("choices") or [{}])[0].get("delta", {})
            chunk = delta.get("content") or ""
            if chunk:
                reply.text += chunk
                on_text(chunk)
        return reply

    def _stream_lines(self, payload: dict) -> Iterator[bytes]:
        """The lines of the streamed reply; if the service rejects a field
        before starting, remove it and retry (as in chat)."""
        for _attempt in range(3):
            lines = self._post_stream(self._url(), payload, self._headers())
            try:
                first = next(lines)
            except StopIteration:
                return
            except ProviderError as e:
                if self._adapt(payload, e):
                    continue
                raise
            yield first
            yield from lines
            return
        yield from self._post_stream(self._url(), payload, self._headers())

    # --- connection test ---
    def offered_models(self) -> list[str]:
        return self._offered_models()

    def _offered_models(self) -> list[str]:
        """The models the service actually offers (GET .../models)."""
        base = self._url().rsplit("/chat/completions", 1)[0]
        req = urllib.request.Request(base + "/models", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - only an extra help
            return []
        entries = data.get("data") if isinstance(data, dict) else data
        return sorted({v.get("id", "") for v in entries or [] if isinstance(v, dict)} - {""})

    def test(self, timeout: float = 25.0) -> tuple[bool, str]:
        if not self._url():
            return False, tr("The service address (endpoint) is missing.")
        if not self._model():
            return False, tr("The model name is missing.")
        if not self.config.api_key and not self._is_local():
            return False, tr("The API key is missing.")
        ok, msg = super().test(timeout) if self.config.api_key else self._test_local(timeout)
        if not ok and any(k in msg.lower() for k in ("model", "modello", "404", "not found")):  # i18n-data
            offered = self._offered_models()
            if offered:
                listing = ", ".join(offered[:12]) + ("…" if len(offered) > 12 else "")
                msg += " " + tr("Available models: {models}").format(models=listing)
        return ok, msg

    def _test_local(self, timeout: float) -> tuple[bool, str]:
        """Like the normal test, but for a local service without a key (the
        base class test stops right away if the key is missing)."""
        prev_tokens, prev_timeout = self.config.max_tokens, self.timeout
        self.config.max_tokens, self.timeout = 16, timeout
        try:
            self.chat([Message(role="user", content="ok")])
            return True, tr("Connected (model {model}).").format(model=self._model())
        except ProviderError as e:
            return False, str(e)
        finally:
            self.config.max_tokens, self.timeout = prev_tokens, prev_timeout
