# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — ZETA.

Ties together the provider, the action engine and memory. Handles the
conversation turn with tools (allowlist) and confirmation for level 3/4 actions.
"""
from __future__ import annotations

import re
import threading
from typing import Callable

from i18n import language, speaking, tr
from i18n_data import load

from . import context, intents, websearch
from .providers.ollama import InsufficientMemoryError
from .actions import ActionEngine, ActionResult
from .memory import HISTORY_BUDGET, HISTORY_TURNS, MAX_TURNS, Memory, trim_history
from .providers.base import (CancelToken, Canceled, ProviderError, Message, Provider, Reply,
                             ToolCall)
from .registry import DEFAULT_SYSTEM, REPLY_LANGUAGE, Registry, language_name, load_settings
from .agent import agent as _agent
from .agent.understanding import understanding as _understand

# Actions from the old recognizer that are still useful and safe (the new
# agent handles the rest, with verification): web and file search, accent
# color, screen off, information. "Knowledge" answers (action None, e.g.
# «how do I open the terminal») remain valid.
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
        # one request at a time (see respond)
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._issued = 0
        self._canceled_upto = 0
        self._token: CancelToken | None = None
        self._notes = []
        self.last_turn = self._fresh_turn()

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

    # --- one request at a time -------------------------------------------
    def cancel(self) -> None:
        """Stop the request in progress, from any thread: its connection is
        closed (the HTTP stream really stops) and its turn is discarded."""
        with self._state_lock:
            self._canceled_upto = self._issued
            token = self._token
        if token is not None:
            token.cancel()

    def _cancel_older(self, ticket: int) -> None:
        with self._state_lock:
            self._canceled_upto = max(self._canceled_upto, ticket - 1)
            token = self._token
        if token is not None:
            token.cancel()

    def _canceled(self) -> bool:
        token = self._token
        return token is not None and token.canceled

    def respond(self, text: str,
                confirm: Callable[[ActionResult], bool] | None = None,
                allow_ai: bool = True,
                on_text: Callable[[str], None] | None = None,
                consent: Callable[[list], str | None] | None = None) -> str:
        """A full turn: local commands first, then (if needed) the AI model.

        One request per conversation: a new one cancels the one still running
        (no duplicate replies, no two requests fighting over the history).
        `consent(services)` asks «Search the web?» and returns "yes",
        "always", "no" or None. After the call, `last_turn` tells the
        interface what else to show (sources, an offer to use the local
        model, whether the turn was canceled).
        """
        with self._state_lock:
            self._issued += 1
            ticket = self._issued
        self._cancel_older(ticket)
        if not self._lock.acquire(timeout=30):
            return tr("ZETA is still finishing the previous request. Try again in a moment.")
        try:
            with self._state_lock:
                canceled = ticket <= self._canceled_upto
                self._token = CancelToken()
            self.last_turn = self._fresh_turn()
            if canceled:
                self.last_turn["canceled"] = True
                return tr("Request canceled.")
            self.last_turn["language"] = self._reply_language(text)
            with speaking(self.last_turn["language"]):
                return self._respond(text, confirm, allow_ai, on_text, consent)
        finally:
            with self._state_lock:
                self._token = None
            self.provider.cancel_token = None
            self._lock.release()

    @staticmethod
    def _reply_language(text: str):
        """Language of ZETA's own texts for this question (confirmations,
        quick answers, notes): the one the user wrote in when it is clearly a
        different language with a ZETA translation, unless Settings › AI ›
        Reply language says "always the system language". None = system."""
        if load_settings().get(REPLY_LANGUAGE) == "system":
            return None
        lang = websearch.clear_language(text)
        return lang if lang and lang != language() else None

    @staticmethod
    def _fresh_turn() -> dict:
        # offer: id of a provider ZETA proposes for this question after a
        # failure ("ollama", or an online service with a key): only proposed,
        # used only if the user accepts (respond_with). language: the one of
        # ZETA's texts for this turn (None = system), for the notes shown
        # with the answer
        return {"sources": [], "offer": "", "canceled": False, "error": "", "web": "",
                "language": None}

    def respond_with(self, provider_id: str, text: str, **kw) -> str:
        """Ask ONE question to another provider, because the user chose it
        (the «Ask …» button after a failure); then back to the usual one."""
        previous = self.provider
        self.provider = self.registry.get(provider_id)
        try:
            return self.respond(text, **kw)
        finally:
            self.provider = previous

    def _respond(self, text, confirm, allow_ai, on_text, consent) -> str:
        empty = self._says_nothing(text)
        if empty is not None:
            return empty
        self.provider.cancel_token = self._token
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
            if self._canceled():
                self.last_turn["canceled"] = True
                return tr("Request canceled.")
            if actions:
                answer = _agent.run_all(actions, confirm, origin="model")
                self.memory.save_turn(text, answer, operation=True)
                return answer
        return self.ask(text, on_text=on_text, confirm=confirm, consent=consent)

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
            confirm: Callable[[ActionResult], bool] | None = None,
            consent: Callable[[list], str | None] | None = None) -> str:
        """A full turn: send, any tool calls, final reply.

        `on_text` receives the pieces of the reply as they arrive, when the
        provider supports it (streaming); otherwise it is called once, at the
        end.
        """
        prov = self.provider
        if self._token is None:                  # called directly, not through respond()
            self._token = CancelToken()
        prov.cancel_token = self._token
        if not prov.available():
            return self._not_ready(prov)
        settings = load_settings()
        web, sources = self._web_context(text, settings, consent, prov)
        if self._canceled():
            self.last_turn["canceled"] = True
            return tr("Request canceled.")
        self.last_turn["web"] = web
        base = settings.get("system") or DEFAULT_SYSTEM
        always = ""
        if settings.get(REPLY_LANGUAGE) == "system":
            always = language_name(language())
        prov.config.system = context.system_prompt(base, web=web, sources=sources,
                                                   reply_language=websearch.clear_language(text),
                                                   always_language=always)
        self._notes = []

        start = len(self.history)
        self.history.append(Message("user", text))
        streaming = bool(on_text and not getattr(prov, "uses_tools", True)
                         and getattr(prov.config, "stream", True))
        executed = False
        if streaming:
            reply = self._stream_turn(on_text)
        else:
            tools = self.engine.tool_specs()
            # first round (with tools; no streaming because a tool may be needed)
            reply = self._turn(tools)
            # any requested actions
            guard = 0
            executed = bool(reply.tool_calls)
            while reply.tool_calls and guard < 6 and not self._canceled():
                guard += 1
                results = self._execute_tools(reply.tool_calls, confirm)
                self.history.append(Message("assistant", self._describe_calls(reply)))
                self.history.append(Message("user", self._format_results(results)))
                reply = self._turn(tools)

        if reply.error == "canceled" or self._canceled():
            del self.history[start:]
            self.last_turn["canceled"] = True
            return tr("Request canceled.")
        if reply.error:
            # an error is not an answer: it stays out of the history (the
            # model would read it back next time) and the user is told what
            # can be done
            del self.history[start:]
            self.last_turn["error"] = reply.error
            return self._with_offer(reply.text)
        final = reply.text.strip()
        if not final and not executed:
            del self.history[start:]
            self.last_turn["error"] = "empty"
            return tr("The model sent an empty reply. Try again, or ask in another way.")
        if on_text and not streaming and final and not self._is_raw_tool_call(final):
            on_text(final)
        answer = self._close_turn(text, final, start, executed)
        if web == "sources":
            self.last_turn["sources"] = sources
        elif web == "off":
            self._notes.append(tr("(Not verified online: web search is off. You can turn it on "
                                  "in Settings › AI.)"))
        elif web == "failed":
            self._notes.append(tr("(Not verified online: the web search found no useful source, "
                                  "or the network is unavailable.)"))
        return "\n\n".join([answer] + self._notes) if answer else answer

    # --- context for the model ---------------------------------------------
    def _window(self) -> list[Message]:
        """The history sent with this request: the latest turns that fit the
        budget of this kind of model (memory.trim_history)."""
        kind = "local" if self.provider.config.kind == "local" else "cloud"
        return trim_history(self.history, HISTORY_TURNS[kind], HISTORY_BUDGET[kind])

    def _web_context(self, text: str, settings: dict, consent, prov) -> tuple[str, list]:
        """("", []) for ordinary questions; for time-sensitive ones the state
        of the web lookup ("sources", "off", "failed", "provider") and the
        sources found. Only the question goes to the search service."""
        if not websearch.is_time_sensitive(text):
            return "", []
        if prov.config.name == "perplexity":
            return "provider", []                    # it searches the web by itself
        state = websearch.mode(settings)
        if state == "ask":
            choice = None
            if consent is not None:
                try:
                    choice = consent(websearch.services(settings))
                except Exception:  # noqa: BLE001 - no answer = no search
                    choice = None
            if choice in ("always", "no"):
                try:
                    websearch.save_choice(choice)
                except OSError:
                    pass
            if choice not in ("yes", "always"):
                return "off", []
        elif state == "off":
            return "off", []
        try:
            sources, _reachable = websearch.lookup(text, settings, lang=language(), token=self._token)
        except Canceled:
            return "failed", []
        return ("sources", sources) if sources else ("failed", [])

    def _not_ready(self, prov: Provider) -> str:
        """The chosen AI can't answer at all: say why, without sending the
        question anywhere else."""
        self.last_turn["error"] = "setup"
        if prov.config.kind == "local":
            if getattr(prov, "list_models", lambda: [])():
                from . import resources
                need = prov._model_gb() if hasattr(prov, "_model_gb") else 0.0
                return self._with_offer(resources.memory_reason(need))
            return self._with_offer(NOT_CONFIGURED)
        if prov.config.name == "custom":
            msg = tr("The custom service needs an address, a model and, for an online "
                     "service, a key: set them in Settings › AI.")
        else:
            msg = tr("{name} has no API key yet. Enter it in Settings › AI, or choose another "
                     "AI there.").format(name=prov.config.label)
        return self._with_offer(msg)

    def _with_offer(self, message: str) -> str:
        """After a failure, OFFER the other kind of AI; never switch by
        ourselves. Online service failed: the local model, if installed.
        Local model failed: an online service with a key, if any; the
        question goes there only if the user accepts, for that question."""
        try:
            if self.provider.config.kind == "cloud":
                other = "ollama" if self.registry.get("ollama").list_models() else ""
            else:
                other = self.registry.cloud_offer()
        except Exception:  # noqa: BLE001
            other = ""
        if not other:
            return message
        self.last_turn["offer"] = other
        if other == "ollama":
            return message + "\n" + tr("You can ask the local model instead: the question stays on "
                                        "this computer.")
        from .registry import CATALOG
        return message + "\n" + tr("You can ask {name} instead, for this question only: it would "
                                    "be sent to that online service.").format(name=CATALOG[other][1])

    # A small model sometimes writes a function call as text instead of
    # answering: {"type":"function","name":...}. Showing it helps nobody, and
    # saving it in the history is worse: the model reads it back and keeps
    # imitating it in later replies (actually observed).
    @staticmethod
    def _is_raw_tool_call(text: str) -> bool:
        t = text.lstrip()[:120].replace(" ", "")
        return t.startswith("{") and ('"function"' in t or t.startswith('{"name":'))

    # «I opened Firefox» said by the model when no action ran is a lie: the
    # model doesn't touch the computer. The reply is kept, but we say clearly
    # that nothing happened. The "I did it" phrases are in Italian and English
    # (the model answers in the user's language): language data in
    # assistant.json (see i18n_data.py).
    _PROMISE = re.compile(load("assistant")["promise"])
    # a negation just before the phrase: the sentence says nothing was done
    _NEGATION_BEFORE = re.compile(load("assistant")["negation_before"])

    @classmethod
    def _honest(cls, final: str, executed: bool) -> str:
        if executed or not final:
            return final
        # «I didn't open anything» is honest: only affirmative sentences count
        promises = [m for m in cls._PROMISE.finditer(final)
                    if not cls._NEGATION_BEFORE.search(final[max(0, m.start() - 8):m.start()])]
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
        self._close_history()
        self.memory.save_turn(text, final)
        return final

    # --- internals ---
    def _close_history(self) -> None:
        """The conversation kept in memory stays bounded."""
        limit = MAX_TURNS * 2
        if len(self.history) > limit:
            self.history = self.history[-limit:]
            while self.history and self.history[0].role != "user":
                self.history.pop(0)

    def _error_reply(self, e: ProviderError) -> Reply:
        return Reply(text=str(e), error=getattr(e, "kind", "error") or "error")

    def _stream_turn(self, on_text: Callable[[str], None]) -> Reply:
        """A streaming round. Errors become a readable reply, as in `_turn`;
        if streaming breaks off halfway, keep what has already arrived and
        say the rest is missing. No hidden second request: a failed stream
        is not sent again without streaming."""
        received: list[str] = []

        def chunk(c: str) -> None:
            received.append(c)
            on_text(c)

        for attempt in range(2):
            try:
                return self.provider.stream(self._window(), chunk)
            except InsufficientMemoryError as e:
                return Reply(text=str(e), error="memory")
            except Canceled:
                return Reply(text="".join(received), error="canceled")
            except ProviderError as e:
                if received:
                    return Reply(text="".join(received) + "\n\n" +
                                 tr("(The reply was cut off: {reason})").format(reason=e))
                # the default model no longer exists: one more try with a
                # model the service really offers (a different request)
                if attempt == 0 and self._fall_back_to_other_model(e):
                    continue
                return self._error_reply(e)
            except Exception as e:  # noqa: BLE001 - a bug must not freeze the turn
                if received:
                    return Reply(text="".join(received) + "\n\n" + tr("(The reply was cut off.)"))
                return Reply(text=tr("Unexpected error: {error}").format(error=e), error="error")
        return Reply(text=tr("Unexpected error: {error}").format(error="stream"), error="error")

    def _turn(self, tools) -> Reply:
        try:
            return self.provider.chat(self._window(), tools)
        except InsufficientMemoryError as e:
            # Typical on the live system: little memory and no swap on disk.
            # Say so plainly, instead of making the computer crawl.
            return Reply(text=str(e), error="memory")
        except Canceled:
            return Reply(error="canceled")
        except ProviderError as e:
            # default model that no longer exists: pick one of those the
            # service really offers and retry (once, with the other model)
            if self._fall_back_to_other_model(e):
                try:
                    return self.provider.chat(self._window(), tools)
                except Canceled:
                    return Reply(error="canceled")
                except ProviderError as e2:
                    e = e2
            # the REAL reason (invalid key, model not found, too many
            # requests...), never a silent switch to another service
            return self._error_reply(e)
        except Exception:  # noqa: BLE001
            if not self.provider.available():
                return Reply(text=NOT_CONFIGURED, error="setup")
            return Reply(text=tr("I can't reach {provider} right now. Check your Internet connection "
                                 "or the setup in Settings › AI.").format(provider=self.provider_label()),
                         error="network")

    def _fall_back_to_other_model(self, e: "ProviderError") -> bool:
        """Only if the user hasn't picked a model (the default is in use) and
        the service says the model doesn't exist. The model found is saved,
        and the reply says so."""
        msg = str(e).lower()
        if self.provider.config.model or e.status not in (400, 404):
            return False
        if getattr(e, "kind", "") != "model" and not any(
                k in msg for k in load("assistant")["model_error_words"]):
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
        notes = getattr(self, "_notes", None)
        if notes is not None:
            notes.append(tr("(The default model of {name} is no longer available: from now on "
                            "ZETA uses {model}.)").format(name=self.provider.config.label, model=chosen))
        return True

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
