# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — ZETA.

Ties together the provider, the action engine and memory. Handles the
conversation turn with tools (allowlist) and confirmation for level 3/4 actions.
"""
from __future__ import annotations

import re
from typing import Callable

from i18n import tr

from . import intents
from .providers.ollama import InsufficientMemoryError
from .actions import ActionEngine, ActionResult
from .memory import Memory
from .providers.base import ProviderError, Message, Provider, Reply, ToolCall
from .registry import Registry
from .agent import agent as _agent
from .agent.understanding import understanding as _understand

# Actions from the old recognizer that are still useful and safe (the new
# agent handles the rest, with verification): web and file search, accent
# color, screen off, information. "Knowledge" answers (action None, e.g.
# «come apro il terminale») remain valid.
_LEGACY_OK = {"open_url", "search_content", "set_accent", "screen_off", "system_info", "uptime",
               "current_date", "open_system_monitor", "open_security", "volume_status",
               "battery_status", "disk_usage", "ip_address", "cpu_usage", "memory_usage"}

# actions whose text output IS the answer (information), not just a "done"
_INFO_ACTIONS = {"cpu_usage", "memory_usage", "disk_usage", "ip_address",
                 "uptime", "system_info", "network_status", "list_applications",
                 "security_status", "process_list", "list_windows",
                 "current_time", "current_date", "battery_status",
                 "volume_status", "find_files", "set_volume"}


NOT_CONFIGURED = tr(
    "ZETA isn't connected to a model yet.\n"
    "To use it, open Settings › AI and enter a key for a service (Claude, OpenAI, Gemini),\n"
    "or install Ollama with a local model, which also works without Internet.")


class Assistant:
    def __init__(self, provider: Provider | None = None):
        self.registry = Registry()
        self.provider = provider or self.registry.resolve_default()
        # tools for the models that can call them: the agent's capabilities
        self.engine = _agent.AgentEngine()
        self.old = ActionEngine()
        self.memory = Memory()
        self.history: list[Message] = self._clean(self.memory.load_history())

    @classmethod
    def _clean(cls, history: list[Message]) -> list[Message]:
        """Remove from the history the replies that were function calls written
        as text (and the question that caused them): when the model read them
        back, they pushed it to answer that way again."""
        out: list[Message] = []
        for m in history:
            if m.role == "assistant" and cls._is_raw_tool_call(m.content):
                if out and out[-1].role == "user":
                    out.pop()
                continue
            out.append(m)
        return out

    def local_command(self, text: str,
                      confirm: Callable[[ActionResult], bool] | None = None) -> str | None:
        """Run a command recognized locally, without an AI model.

        First the new agent (real action + verification); then, for the few
        things that only exist there, the old recognizer. None = not a command.
        """
        actions = _understand(text)
        if actions:
            return _agent.run_all(actions, confirm, origin="local")
        intent = intents.parse(text)
        if intent is None or (intent.action is not None and intent.action not in _LEGACY_OK):
            return None
        if intent.action is None:
            # a question with a definite answer (where something is, how to do
            # something): just answer it, without running anything
            return intent.reply
        res = self.old.run(intent.action, intent.args)
        if res.needs_confirmation:
            approved = confirm(res) if confirm else False
            if not approved:
                return tr("Operation canceled.")
            res = self.old.run(intent.action, intent.args, authorized=True)
        if not res.ok:
            return tr("It didn't work: {error}").format(error=res.output)
        out = (res.output or "").strip()
        if out and intent.action in _INFO_ACTIONS:
            return out
        return intent.reply

    def respond(self, text: str,
                confirm: Callable[[ActionResult], bool] | None = None,
                allow_ai: bool = True,
                on_text: Callable[[str], None] | None = None) -> str:
        """A full turn: local commands first, then (if needed) the AI model."""
        empty = self._says_nothing(text)
        if empty is not None:
            return empty
        local = self.local_command(text, confirm)
        if local is not None:
            self.memory.save_turn(text, local, operation=True)
            return local
        if not allow_ai:
            return tr("I didn't understand the command. Try, for example: “open documents”, "
                      "“how much RAM am I using”, “open the terminal”, “close the window”.")
        # local model: it picks an action from the catalog (if the sentence asks
        # for one), otherwise we just chat. Online services use the tools.
        if not getattr(self.provider, "uses_tools", True):
            actions = _agent.choose_with_model(text, self.provider)
            if actions:
                answer = _agent.run_all(actions, confirm, origin="model")
                self.memory.save_turn(text, answer, operation=True)
                return answer
        return self.ask(text, on_text=on_text, confirm=confirm)

    @staticmethod
    def _says_nothing(text: str) -> str | None:
        """Immediately discard input there is nothing to answer to.

        Without this check an empty line, or one made only of symbols, went to
        the language model: tens of seconds of waiting for a meaningless reply.
        """
        t = (text or "").strip()
        if not t:
            return tr("You didn't write anything. Try “open documents”, "
                      "“what time is it”, “how much RAM am I using”.")
        if not any(c.isalnum() for c in t):
            return tr("I didn't understand “{text}”. Try writing it in words: "
                      "“open settings”, “what time is it”.").format(text=t[:30])
        return None

    def provider_label(self) -> str:
        p = self.provider
        if p.config.kind == "local":
            return tr("{name} (local)").format(name=p.config.label)
        return p.config.label

    def ask(self, text: str, on_text: Callable[[str], None] | None = None,
            confirm: Callable[[ActionResult], bool] | None = None) -> str:
        """A full turn: send, any tool calls, final reply.

        `on_text` receives the pieces of the reply as they arrive, when the
        provider supports it (streaming); otherwise it is called once, at the
        end.
        """
        start = len(self.history)
        self.history.append(Message("user", text))
        if (on_text and not getattr(self.provider, "uses_tools", True)
                and getattr(self.provider.config, "stream", True)):
            final = self._stream_turn(on_text).strip()
            return self._close_turn(text, final, start)
        tools = self.engine.tool_specs()

        # first round (with tools; no streaming because a tool may be needed)
        reply = self._turn(tools)
        # any requested actions
        guard = 0
        executed = bool(reply.tool_calls)
        while reply.tool_calls and guard < 6:
            guard += 1
            results = self._execute_tools(reply.tool_calls, confirm)
            self.history.append(Message("assistant", self._describe_calls(reply)))
            self.history.append(Message("user", self._format_results(results)))
            reply = self._turn(tools)

        final = reply.text.strip()
        if on_text and final and not self._is_raw_tool_call(final):
            on_text(final)
        return self._close_turn(text, final, start, executed)

    # A small model sometimes writes a function call as text instead of
    # answering: {"type":"function","name":...}. Showing it helps nobody, and
    # saving it in the history is worse: the model reads it back and keeps
    # imitating it in later replies (actually observed).
    @staticmethod
    def _is_raw_tool_call(text: str) -> bool:
        t = text.lstrip()[:120].replace(" ", "")
        return t.startswith("{") and ('"function"' in t or t.startswith('{"name":'))

    # «Ho aperto Firefox» ("I opened Firefox") said by the model when no
    # action ran is a lie: the model doesn't touch the computer. The reply is
    # kept, but we say clearly that nothing happened.
    # The same phrases in English («I've opened», «Done»): the model answers
    # in the user's language.
    # i18n-data-begin: Italian and English "I did it" phrases
    _PROMISE = re.compile(
        r"(?i)(?:^\s*fatto\b|\b(?:ho|l'ho|li ho|le ho)\s+(?:gia'?\s+|appena\s+)?(?:aperto|chiuso|"
        r"eliminato|cancellato|creato|spostato|copiato|installato|disinstallato|spento|acceso|"
        r"riavviato|avviato|impostato|attivato|disattivato|collegato|scollegato|bloccato|"
        r"salvato|scaricato|rinominato|alzato|abbassato|cambiato)\b"
        r"|^\s*done\b|\bi(?:'ve|\u2019ve| have)?\s+(?:already\s+|just\s+)?(?:opened|closed|deleted|"
        r"removed|created|moved|copied|installed|uninstalled|turned\s+(?:off|on)|switched\s+(?:off|on)|"
        r"restarted|rebooted|started|launched|enabled|disabled|connected|disconnected|locked|saved|"
        r"downloaded|renamed|raised|lowered|changed|muted)\b)")
    # i18n-data-end

    @classmethod
    def _honest(cls, final: str, executed: bool) -> str:
        if executed or not final:
            return final
        # «non ho aperto nulla» ("I didn't open anything") is honest: only
        # affirmative sentences count
        # i18n-data: the Italian negation «non» before the verb
        promises = [m for m in cls._PROMISE.finditer(final)
                    if not re.search(r"(?i)\bnon\s+(?:l'|li\s+|le\s+|lo\s+)?$", final[max(0, m.start() - 8):m.start()])]
        if not promises:
            return final
        return (final + "\n\n" + tr("(Note: I didn't perform any action on the computer. "
                                      "If you want me to, ask for it as a command, for example "
                                      "“open Firefox”.)"))

    def _close_turn(self, text: str, final: str, start: int, executed: bool = False) -> str:
        final = self._honest(final, executed)
        if self._is_raw_tool_call(final):
            # the whole turn stays out of the history: it got no answer
            del self.history[start:]
            return tr("I couldn't understand the request. Try saying it another "
                      "way, or with a command: “open the terminal”, "
                      "“how much RAM am I using”.")
        self.history.append(Message("assistant", final))
        self.memory.save_turn(text, final)
        return final

    # --- internals ---
    def _stream_turn(self, on_text: Callable[[str], None]) -> str:
        """A streaming round. Errors become a readable reply, as in `_turn`;
        if streaming breaks off halfway, keep what has already arrived and
        say the rest is missing."""
        received: list[str] = []

        def chunk(c: str) -> None:
            received.append(c)
            on_text(c)
        try:
            return self.provider.stream(self.history, chunk).text
        except InsufficientMemoryError as e:
            return str(e)
        except Exception:  # noqa: BLE001
            if received:
                return "".join(received) + "\n\n" + tr("(The reply was cut off.)")
            return self._turn([]).text

    def _turn(self, tools) -> Reply:
        try:
            return self.provider.chat(self.history, tools)
        except InsufficientMemoryError as e:
            # Typical on the live system: little memory and no swap on disk.
            # Say so plainly, instead of making the computer crawl.
            return Reply(text=str(e))
        except ProviderError as e:
            # 1) default model that no longer exists: pick one of those the
            #    service really offers and retry
            if self._fall_back_to_other_model(e):
                try:
                    return self.provider.chat(self.history, tools)
                except ProviderError as e2:
                    e = e2
            # 2) online service unreachable: the local model answers
            local = self._local_answer(e)
            if local is not None:
                return local
            # 3) otherwise the REAL reason (invalid key, model not found, too
            #    many requests...): it used to always become "I can't reach…
            #    check your connection", even with a wrong key
            return Reply(text=str(e))
        except Exception:  # noqa: BLE001
            if not self.provider.available():
                return Reply(text=NOT_CONFIGURED)
            return Reply(text=tr("I can't reach {provider} right now. Check your Internet connection "
                                 "or the setup in Settings › AI.").format(provider=self.provider_label()))

    def _fall_back_to_other_model(self, e: "ProviderError") -> bool:
        """Only if the user hasn't picked a model (the default is in use) and
        the service says the model doesn't exist. The model found is saved."""
        msg = str(e).lower()
        if self.provider.config.model or e.status not in (400, 404):
            return False
        if not any(k in msg for k in ("model", "modello", "not found", "non trovato")):  # i18n-data
            return False
        from .providers.base import choose_model
        name = self.provider.config.name
        chosen = choose_model(name, self.provider.offered_models())
        if not chosen:
            return False
        self.provider.config.model = chosen
        try:
            self.registry.set_option(name, "model", chosen)
        except Exception:  # noqa: BLE001 - it still applies to this session
            pass
        return True

    def _local_answer(self, e: "ProviderError") -> Reply | None:
        """No network or service down (not: wrong key, rate limits): if the
        local model is there, it answers, and we say so."""
        if self.provider.config.kind != "cloud" or not e.retryable or e.status == 429:
            return None
        try:
            local = self.registry.get("ollama")
            if not local.available():
                return None
            r = local.chat(self.history, None)
        except Exception:  # noqa: BLE001
            return None
        r.text = (tr("({provider} isn't responding: {reason} The local model answered instead.)").format(
            provider=self.provider_label(), reason=str(e).split(":", 1)[-1].strip()) + "\n\n" + r.text)
        return r

    def _execute_tools(self, calls: list[ToolCall],
                       confirm: Callable[[ActionResult], bool] | None) -> list[tuple[str, ActionResult]]:
        out = []
        for call in calls:
            res = self.engine.run(call.name, call.arguments)
            if res.needs_confirmation:
                approved = confirm(res) if confirm else False
                if approved:
                    res = self.engine.run(call.name, call.arguments, authorized=True)
                else:
                    res = ActionResult(False, "Action canceled by the user.")
            out.append((call.name, res))
        return out

    def _describe_calls(self, reply: Reply) -> str:
        return reply.text or "Running the requested actions."

    def _format_results(self, results: list[tuple[str, ActionResult]]) -> str:
        parts = []
        for name, res in results:
            head = "OK" if res.ok else "ERROR"
            parts.append("[%s] %s: %s" % (head, name, res.output))
        return "\n".join(parts)
