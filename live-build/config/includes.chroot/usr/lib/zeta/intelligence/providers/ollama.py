# SPDX-License-Identifier: GPL-3.0-or-later
"""Ollama provider (local models) for ZETA RAYS Intelligence.

ZETA RAYS works even without Internet: if Ollama is running with a compatible
model, ZETA uses it. Detects the installed models.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from i18n import tr

from .base import Message, Provider, Reply, ToolSpec
from .. import resources

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"


class InsufficientMemoryError(RuntimeError):
    """Not enough memory to load the model: better to say so than to hang."""


class OllamaProvider(Provider):
    # The local model doesn't get the actions (ZETA recognizes commands by
    # itself, in intents.py): its replies are always streamed.
    uses_tools = False

    def _base(self) -> str:
        return (self.config.endpoint or DEFAULT_ENDPOINT).rstrip("/")

    def available(self) -> bool:
        """Usable only if Ollama responds AND there is memory for the model.

        Claiming to be available without the memory to load the model means
        getting this provider chosen and then freezing the computer the moment
        the user asks the first question.
        """
        if not resources.memory_for_model() and not self._already_loaded():
            return False
        return bool(self.list_models())

    def test(self, timeout: float = 25.0) -> tuple[bool, str]:
        """Test the local connection without making it load the model.

        The generic test asks a real question: for Ollama that would mean
        loading the model, which on a modest machine takes tens of seconds and
        would make the test time out, looking like a failure. Here we check
        what matters: the service responds, the model exists, memory suffices.
        """
        models = self.list_models()
        if not models:
            return False, tr("Ollama isn't responding at {address}. Check that the service "
                             "is running: systemctl status ollama").format(address=self._base())
        wanted = self._model()
        if wanted and wanted not in models:
            return False, tr("The model “{model}” isn't installed. Available: {models}.").format(
                model=wanted, models=", ".join(models))
        if self._already_loaded():
            return True, tr("Connected, model {model} already in memory (instant replies).").format(
                model=wanted)
        if not resources.memory_for_model():
            return False, tr("Ollama is responding, but there isn't enough free memory to "
                             "load the model: questions would hang.")
        return True, tr("Connected, model {model} ready. The first reply needs to "
                        "load it into memory.").format(model=wanted)

    def _already_loaded(self) -> bool:
        """The model is already in memory: using it costs no extra memory."""
        try:
            with urllib.request.urlopen(self._base() + "/api/ps", timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("models"))
        except (urllib.error.URLError, ValueError, OSError):
            return False

    def preload(self) -> bool:
        """Load the model into memory without generating anything.

        This removes the wait on first use: from cold, the model takes tens of
        seconds to load, then answers in fractions of a second.
        """
        if not resources.memory_for_model():
            return False
        try:
            payload = json.dumps({"model": self._model(), "messages": [],
                                  "keep_alive": self.KEEP_ALIVE}).encode()
            req = urllib.request.Request(self._base() + "/api/chat", data=payload,
                                         headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                resp.read()
            return True
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def list_models(self) -> list[str]:
        """Locally installed models (empty if Ollama isn't running)."""
        try:
            with urllib.request.urlopen(self._base() + "/api/tags", timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except (urllib.error.URLError, ValueError, OSError):
            return []

    def _model(self) -> str:
        if self.config.model:
            return self.config.model
        models = self.list_models()
        return models[0] if models else "llama3.2"

    def _messages(self, messages: list[Message]) -> list[dict]:
        out = []
        if self.config.system:
            out.append({"role": "system", "content": self.config.system})
        # a small local model with a long history loses track and answers
        # old questions: the last few exchanges are enough
        recent = messages[-self.MAX_HISTORY:]
        while recent and recent[0].role != "user":
            recent = recent[1:]
        out.extend({"role": m.role, "content": m.content} for m in recent)
        return out

    MAX_HISTORY = 8

    # Short replies: with a small model a long reply almost always rambles
    # and makes the user wait for nothing.
    MAX_TOKEN = 220

    @property
    def KEEP_ALIVE(self) -> str:          # noqa: N802  (historical name)
        """How long the model stays in memory after the last question.

        It isn't a constant: it depends on how much RAM the computer has.
        Keeping 1.8 GB busy for half an hour on a 4 GB machine is the exact
        recipe for the freezes and slowdowns we want to avoid.
        """
        return resources.keep_alive()

    def _options(self) -> dict:
        opts = {"temperature": self.config.temperature,
               "num_predict": self.config.max_tokens or self.MAX_TOKEN}
        if self.config.context:
            opts["num_ctx"] = self.config.context
        return opts

    def _check_memory(self) -> None:
        if not self._already_loaded() and not resources.memory_for_model():
            raise InsufficientMemoryError(resources.memory_reason())

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> Reply:
        self._check_memory()
        payload = {"model": self._model(), "messages": self._messages(messages),
                   "stream": False, "keep_alive": self.KEEP_ALIVE,
                   "options": self._options()}
        data = self._post(self._base() + "/api/chat", payload, {"content-type": "application/json"})
        reply = Reply(text=data.get("message", {}).get("content", ""))
        reply.input_tokens = data.get("prompt_eval_count", 0)
        reply.output_tokens = data.get("eval_count", 0)
        return reply

    def stream(self, messages: list[Message],
               on_text: Callable[[str], None]) -> Reply:
        self._check_memory()
        payload = {"model": self._model(), "messages": self._messages(messages),
                   "stream": True, "keep_alive": self.KEEP_ALIVE,
                   "options": self._options()}
        reply = Reply()
        for raw in self._post_stream(self._base() + "/api/chat", payload,
                                     {"content-type": "application/json"}):
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            chunk = ev.get("message", {}).get("content", "")
            if chunk:
                reply.text += chunk
                on_text(chunk)
            if ev.get("done"):
                reply.input_tokens = ev.get("prompt_eval_count", reply.input_tokens)
                reply.output_tokens = ev.get("eval_count", reply.output_tokens)
        return reply
