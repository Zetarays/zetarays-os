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

from .base import Message, Provider, ProviderError, Reply, ToolSpec
from .. import resources

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"

# The local model ZETA uses when the user has not picked one in Settings › AI.
# This is the ONLY place to change it (the model shipped in the image is set
# up by the build hooks, separately). If it is not installed, the first
# installed model is used. Chosen for 2.1 after a benchmark: Qwen3-4B-Instruct-2507
# (Apache-2.0, 2.5 GB file, about 3.7 GB loaded, no "thinking" mode).
DEFAULT_MODEL = "qwen3:4b-instruct"


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
        models = self._tags()
        if not models:
            return False
        if not resources.memory_for_model(self._model_gb(models)) and not self._already_loaded():
            return False
        return True

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
        if not resources.memory_for_model(self._model_gb()):
            return False, tr("Ollama is responding, but there isn't enough free memory to "
                             "load the model: questions would hang.")
        return True, tr("Connected, model {model} ready. The first reply needs to "
                        "load it into memory.").format(model=wanted)

    def _already_loaded(self) -> bool:
        """Our model is already in memory: using it costs no extra memory.
        (Another model in memory does not count: ours would need room too.)"""
        try:
            with urllib.request.urlopen(self._base() + "/api/ps", timeout=2.0) as resp:
                data = json.loads(resp.read(256 * 1024).decode("utf-8"))
            names = {m.get("name") or m.get("model") for m in data.get("models") or []}
            return bool(names) and self._model() in names
        except (urllib.error.URLError, ValueError, OSError, AttributeError):
            return False

    def _tags(self) -> dict:
        """Installed models: {name: file size in GB} (empty if Ollama isn't running)."""
        try:
            with urllib.request.urlopen(self._base() + "/api/tags", timeout=2.0) as resp:
                data = json.loads(resp.read(1024 * 1024).decode("utf-8"))
            return {m["name"]: (m.get("size") or 0) / 1e9 for m in data.get("models", [])
                    if m.get("name")}
        except (urllib.error.URLError, ValueError, OSError, KeyError, TypeError, AttributeError):
            return {}

    def _model_gb(self, tags: dict | None = None) -> float:
        """Memory the model in use needs once loaded (estimated from its file)."""
        tags = self._tags() if tags is None else tags
        return resources.model_memory_gb(tags.get(self._model_from(list(tags)), 0.0))

    def preload(self) -> bool:
        """Load the model into memory without generating anything.

        This removes the wait on first use: from cold, the model takes tens of
        seconds to load, then answers in fractions of a second. The system
        prompt is read now too (the same text every question starts with):
        the model keeps it in its cache, so the first question only costs
        its own tokens.
        """
        if not resources.memory_for_model(self._model_gb()):
            return False
        try:
            # same options as the questions: a different context size would
            # make Ollama load the model a second time at the first question
            from ..registry import current_system_prompt
            payload = json.dumps({"model": self._model(), "stream": False,
                                  "messages": [{"role": "system", "content": current_system_prompt()}],
                                  "keep_alive": self.KEEP_ALIVE,
                                  "options": dict(self.load_options(), num_predict=1)}).encode()
            req = urllib.request.Request(self._base() + "/api/chat", data=payload,
                                         headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                resp.read()
            return True
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def list_models(self) -> list[str]:
        """Locally installed models (empty if Ollama isn't running)."""
        return list(self._tags())

    def _model(self) -> str:
        if self.config.model:
            return self.config.model
        return self._model_from(self.list_models())

    def _model_from(self, models: list[str]) -> str:
        if self.config.model:
            return self.config.model
        if not models or DEFAULT_MODEL in models:
            return DEFAULT_MODEL
        return models[0]

    def _messages(self, messages: list[Message]) -> list[dict]:
        out = []
        if self.config.system:
            out.append({"role": "system", "content": self.config.system})
        # The history arrives already limited by the assistant (a few turns,
        # cut in blocks: memory.history_budget, Assistant._window). A second
        # sliding limit here (the last 8 messages) moved the start of the
        # prompt at every question and made the model reread everything.
        recent = list(messages)
        while recent and recent[0].role != "user":
            recent = recent[1:]
        out.extend({"role": m.role, "content": m.content} for m in recent)
        return out

    # Short replies: with a small model a long reply almost always rambles
    # and makes the user wait for nothing.
    MAX_TOKEN = 220

    @property
    def KEEP_ALIVE(self) -> str:          # noqa: N802  (historical name)
        """How long the model stays in memory after the last question.

        It isn't a constant: it depends on how much RAM the computer has.
        Keeping 3.7 GB busy for half an hour on an 8 GB machine is the exact
        recipe for the freezes and slowdowns we want to avoid.
        """
        return resources.keep_alive()

    def load_options(self) -> dict:
        """The options that decide how the model is loaded (Ollama reloads the
        model when they change): every request must send the same ones."""
        return {"num_ctx": self.config.context} if self.config.context else {}

    def _options(self) -> dict:
        opts = {"temperature": self.config.temperature,
               "num_predict": self.config.max_tokens or self.MAX_TOKEN}
        opts.update(self.load_options())
        return opts

    def _http_error(self, code: int, body: str, headers=None) -> ProviderError:
        err = super()._http_error(code, body, headers)
        if err.kind == "model" or (code == 404 and "not found" in body.lower()):
            return ProviderError(tr("The local model “{model}” isn't installed. Choose an installed "
                                    "one in Settings › AI.").format(model=self._model()),
                                 status=code, kind="model")
        return err

    def _check_memory(self) -> None:
        if not self._already_loaded():
            need = self._model_gb()
            if not resources.memory_for_model(need):
                raise InsufficientMemoryError(resources.memory_reason(need))

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> Reply:
        self._check_memory()
        payload = {"model": self._model(), "messages": self._messages(messages),
                   "stream": False, "keep_alive": self.KEEP_ALIVE,
                   "options": self._options()}
        data = self._post(self._base() + "/api/chat", payload, {"content-type": "application/json"})
        reply = Reply(text=data.get("message", {}).get("content", ""))
        reply.input_tokens = data.get("prompt_eval_count", 0)
        reply.output_tokens = data.get("eval_count", 0)
        self._record_speed(data)
        return reply

    @staticmethod
    def _record_speed(ev: dict) -> None:
        """Ollama's timings of this request: the reading speed decides how
        much history the next questions send (memory.history_budget)."""
        try:
            resources.record_speed(int(ev.get("prompt_eval_count") or 0),
                                   (ev.get("prompt_eval_duration") or 0) / 1e9,
                                   int(ev.get("eval_count") or 0),
                                   (ev.get("eval_duration") or 0) / 1e9)
        except (TypeError, ValueError):
            pass

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
            if ev.get("error"):
                raise self._stream_failed(ev.get("error"))
            chunk = ev.get("message", {}).get("content", "")
            if chunk:
                reply.text += chunk
                on_text(chunk)
            if ev.get("done"):
                reply.input_tokens = ev.get("prompt_eval_count", reply.input_tokens)
                reply.output_tokens = ev.get("eval_count", reply.output_tokens)
                self._record_speed(ev)
        return reply
