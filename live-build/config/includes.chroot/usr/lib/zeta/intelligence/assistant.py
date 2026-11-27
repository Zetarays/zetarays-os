# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — ZETA.

Ties together the local model, the action engine and memory. A turn: local
commands first (actions, memory commands), then the action chooser of the
local model, then the conversation, streamed. Everything runs on this
computer: there is no online AI service to fall back to.
"""
from __future__ import annotations

import re
import threading
from typing import Callable

from i18n import language, speaking, tr
from i18n_data import load

from . import context, intents, store, websearch
from .providers.ollama import InsufficientMemoryError
from .actions import ActionEngine, ActionResult
from .memory import HISTORY_TURNS, MAX_TURNS, Memory, approx_tokens, history_budget, trim_history
from .providers.base import CancelToken, Canceled, ProviderError, Message, Provider, Reply
from .registry import REPLY_LANGUAGE, Registry, always_language, current_system_prompt, load_settings
from .agent import agent as _agent
from .agent.understanding import is_definition_question, understanding as _understand

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
    "ZETA has no local model to answer with yet.\n"
    "Open Settings › AI to start Ollama or download a model: it runs on this computer, "
    "also without Internet.")

# How long a verified fact of the local reference is used without looking
# the question up on the web (the reference is renewed with every release)
REFERENCE_FRESH_DAYS = 180

# «remember that…», «forget…», «what do you know about me?» (language data)
_MEMORY_COMMANDS = {kind: [re.compile(p, re.I) for p in patterns]
                    for kind, patterns in load("memory")["commands"].items()}


class Assistant:
    def __init__(self, provider: Provider | None = None):
        self.registry = Registry()
        self.provider = provider or self.registry.resolve_default()
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
        if is_definition_question(text):
            return None                       # «what is a CPU?» is for the model
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
        interface what else to show (sources, the model that answered,
        whether the turn was canceled).
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
            restore = getattr(self, "_restore_model", None)
            if restore is not None:                  # back to the usual model
                restore[0].config.model = restore[1]
                self._restore_model = None
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
        # language: the one of ZETA's texts for this turn (None = system),
        # for the notes shown with the answer. model: the local model that
        # answered, when it is not the usual one (a smaller fallback).
        # reference: local reference entries used for a current fact.
        return {"sources": [], "reference": [], "canceled": False, "error": "", "web": "",
                "language": None, "model": ""}

    def _respond(self, text, confirm, allow_ai, on_text, consent) -> str:
        empty = self._says_nothing(text)
        if empty is not None:
            return empty
        self.provider.cancel_token = self._token
        remembered = self.memory_command(text)
        if remembered is not None:
            return remembered
        # «what's on my screen?», «summarize the file …»: the text is read
        # here, the local model answers (reading.py)
        if allow_ai:
            read = self.read_and_ask(text, on_text=on_text, confirm=confirm, consent=consent)
            if read is not None:
                return read
        local = self.local_command(text, confirm)
        if local is not None:
            self.memory.save_turn(text, local, operation=True)
            return local
        if not allow_ai:
            return tr("I didn't understand the command. Try, for example: “open documents”, "
                      "“how much RAM am I using”, “open the terminal”, “close the window”.")
        # the model picks an action from the catalog (only if the sentence
        # talks about one), otherwise we just chat; «what is a CPU?» is a
        # question about the thing, never an action on it
        actions = None if is_definition_question(text) else _agent.choose_with_model(text, self.provider)
        if self._canceled():
            self.last_turn["canceled"] = True
            return tr("Request canceled.")
        if actions:
            answer = _agent.run_all(actions, confirm, origin="model")
            self.memory.save_turn(text, answer, operation=True)
            return answer
        return self.ask(text, on_text=on_text, confirm=confirm, consent=consent)

    def memory_command(self, text: str) -> str | None:
        """«remember that…», «forget…», «what do you know about me?»: answered
        from the local store, without the model. None = not one of them."""
        t = " ".join((text or "").split()).rstrip(" .!")
        for kind in ("list", "forget", "remember"):
            for pattern in _MEMORY_COMMANDS.get(kind, []):
                m = pattern.match(t)
                if m:
                    return self._run_memory_command(kind, (m.groupdict().get("text") or "").strip())
        return None

    def _run_memory_command(self, kind: str, what: str) -> str:
        if not self.memory.enabled or not self.memory.long_term:
            return tr("Long-term memory is off. You can turn it on in Settings › AI › Memory.")
        try:
            if kind == "list":
                facts = self.memory.facts()
                if not facts:
                    return tr("You haven't asked me to remember anything yet. Say, for example: "
                              "“remember that I prefer short answers”.")
                return tr("This is what you asked me to remember:") + "\n" + "\n".join(
                    "• " + f.text for f in facts[:30])
            if kind == "forget":
                gone = self.memory.forget(what)
                if not gone:
                    return tr("I found nothing like that among the things you asked me to remember.")
                return tr("Forgotten:") + "\n" + "\n".join("• " + g for g in gone)
            if not store.terms(what):            # «remember that» with nothing after it
                return tr("Tell me what to remember, for example: “remember that I live in Bologna”.")
            outcome, stored = self.memory.remember(what)
        except Exception as e:  # noqa: BLE001 - the store is a file: it can fail
            return tr("I couldn't use the memory: {error}").format(error=e)
        if outcome == "added":
            return tr("I'll remember it: {text}").format(text=stored)
        if outcome == "updated":
            return tr("Updated: {text}").format(text=stored)
        if outcome == "duplicate":
            return tr("I already remember it: {text}").format(text=stored)
        if outcome == "full":
            return tr("The memory is full. Remove something in Settings › AI › Memory.")
        return tr("Tell me what to remember, for example: “remember that I live in Bologna”.")

    def read_and_ask(self, text: str, on_text: Callable[[str], None] | None = None,
                     confirm: Callable[[ActionResult], bool] | None = None,
                     consent: Callable[[list], str | None] | None = None) -> str | None:
        """«What's on my screen?», «translate what I'm looking at»,
        «summarize the file “…”»: read the text (screen: the window in front,
        recognized locally; file: its text), then the local model answers
        the request with it. None = not such a request."""
        from . import reading
        request = reading.parse(text)
        if request is None:
            return None
        kind, path = request
        if kind == "which_file":
            return tr("Which file? Write its path (for example “summarize ~/Documents/report.pdf”), "
                      "or right-click it in Files and choose “Ask ZETA to Summarize”.")
        if kind == "missing":
            return tr("I can't find the file “{path}”.").format(path=path)
        try:
            doc = reading.screen_text() if kind == "screen" else reading.file_text(path)
        except reading.ReadError as e:
            return str(e)
        if self._canceled():
            self.last_turn["canceled"] = True
            return tr("Request canceled.")
        if not reading.has_words(doc.text):
            if kind == "screen":
                return tr("I found no text in the window in front ({window}). I can read the "
                          "text on the screen, but I can't see pictures: there is no image model "
                          "on this computer.").format(window=doc.source)
            return tr("I found no text in “{name}”. If it is a scanned document, use "
                      "“Copy Text from Image” on it first (right-click in Files).").format(name=doc.source)
        # a summary or a translation needs a longer answer than a chat reply
        config = self.provider.config
        usual = config.max_tokens
        config.max_tokens = max(usual or 0, reading.ANSWER_TOKENS)
        try:
            return self.ask(text, on_text=on_text, confirm=confirm, consent=consent, document=doc)
        finally:
            config.max_tokens = usual

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
        return tr("{name} (local)").format(name=self.provider.config.label)

    def ask(self, text: str, on_text: Callable[[str], None] | None = None,
            confirm: Callable[[ActionResult], bool] | None = None,
            consent: Callable[[list], str | None] | None = None,
            document=None) -> str:
        """A conversation turn with the local model.

        `on_text` receives the pieces of the reply as they arrive (streaming);
        without it, or with streaming off in Settings, it is called once, at
        the end. `document`: a reading.Document the request is about (the
        screen, a file): its text goes with this question only, cut to what
        the model reads quickly; the memory keeps the question, not the text.
        """
        prov = self.provider
        if self._token is None:                  # called directly, not through respond()
            self._token = CancelToken()
        prov.cancel_token = self._token
        self._notes = []
        if not prov.available():
            fallback = self._smaller_model(prov)
            if not fallback:
                return self._not_ready(prov)
        settings = load_settings()
        if document is not None:
            web, sources, reference = "", [], []     # the answer is in the text read
        else:
            web, sources, reference = self._web_context(text, settings, consent)
        if self._canceled():
            self.last_turn["canceled"] = True
            return tr("Request canceled.")
        self.last_turn["web"] = web
        # fixed system prompt + a note with what changes, kept with the
        # question in the history: the local model rereads nothing it has
        # already read (context.py explains why)
        prov.config.system = current_system_prompt(settings)
        note = context.turn_note(web=web, sources=sources, reference=reference,
                                 memories=self.memory.recall(text),
                                 reply_language=websearch.clear_language(text),
                                 always_language=always_language(settings))

        start = len(self.history)
        asked = text
        if document is not None:
            from . import reading
            body, cut = reading.trim(document.text, reading.budget(prov.config.context,
                                                                   prov.config.max_tokens))
            asked = reading.frame(document, body, cut) + "\n\n" + text
            if cut:
                self._notes.append(tr("(I read only the first part of the text: {shown} of {total} "
                                      "characters.)").format(shown=len(body), total=len(document.text)))
        self.history.append(Message("user", context.with_note(asked, note)))
        if document is not None:
            # the text goes with this question only: the earlier turns stay
            # out of this request (the context of a small computer is short)
            self._window_first = self.history[-1]
        streaming = bool(on_text and getattr(prov.config, "stream", True))
        reply = self._stream_turn(on_text) if streaming else self._turn()
        if reply.error == "memory" and not self._canceled():
            # not enough free memory for the usual model: a smaller installed
            # local model answers this question, if one fits
            if self._smaller_model(prov):
                reply = self._stream_turn(on_text) if streaming else self._turn()

        if reply.error == "canceled" or self._canceled():
            del self.history[start:]
            self.last_turn["canceled"] = True
            return tr("Request canceled.")
        if reply.error:
            # an error is not an answer: it stays out of the history (the
            # model would read it back next time)
            del self.history[start:]
            self.last_turn["error"] = reply.error
            return reply.text
        final = context.strip_note_echo(reply.text).strip()
        if not final:
            del self.history[start:]
            self.last_turn["error"] = "empty"
            return tr("The model sent an empty reply. Try again, or ask in another way.")
        if on_text and not streaming and not self._is_raw_tool_call(final):
            on_text(final)
        answer = self._close_turn(text, final, start)
        if web == "sources":
            self.last_turn["sources"] = sources
            try:
                store.remember_sources(sources)
            except Exception:  # noqa: BLE001 - keeping sources is a bonus, not a duty
                pass
        elif web == "reference":
            self.last_turn["reference"] = reference
        elif web == "off":
            self._notes.append(tr("(Not verified online: web search is off. You can turn it on "
                                  "in Settings › AI.)"))
        elif web == "failed":
            self._notes.append(tr("(Not verified online: the web search found no useful source, "
                                  "or the network is unavailable.)"))
        return "\n\n".join([answer] + self._notes) if answer else answer

    def _smaller_model(self, prov) -> str:
        """Switch this turn to a smaller installed model that fits the free
        memory now; "" when there is none. The usual model comes back with
        the next question (respond() restores it)."""
        try:
            smaller = prov.fallback_model()
        except Exception:  # noqa: BLE001
            smaller = ""
        if not smaller:
            return ""
        usual = prov._model()
        self._restore_model = (prov, prov.config.model)
        prov.config.model = smaller
        self.last_turn["model"] = smaller
        self._notes.append(tr("(Answered by the smaller model {small}: there isn't enough free "
                              "memory for {usual} right now.)").format(small=smaller, usual=usual))
        return smaller

    # --- context for the model ---------------------------------------------
    def _window(self) -> list[Message]:
        """The history sent with this request: the latest turns that fit the
        budget (memory.trim_history).

        The window keeps its first message as long as it fits, and when it
        no longer does it is cut down to half the budget: dropping the oldest
        turn at every question would change the beginning of the prompt every
        time, and a local model would reread the whole conversation for each
        question instead of only the new one."""
        budget = history_budget()
        turns = HISTORY_TURNS
        first = getattr(self, "_window_first", None)
        start = next((i for i, m in enumerate(self.history) if m is first), None)
        if start is not None:
            window = self.history[start:]
            if (sum(approx_tokens(m.content) for m in window) <= budget
                    and sum(1 for m in window if m.role == "user") <= turns):
                return window
        window = trim_history(self.history, max(1, turns // 2), budget // 2)
        self._window_first = window[0] if window else None
        return window

    def _web_context(self, text: str, settings: dict, consent) -> tuple[str, list, list]:
        """("", [], []) for ordinary questions; for time-sensitive ones the
        state of the lookup ("sources", "reference", "off", "failed"), the web
        sources found and the local reference entries. Only the question goes
        to the search service; the local reference never leaves the computer."""
        if not websearch.is_time_sensitive(text):
            # a question about Linux or this system: the command's manual page
            # (offline) and, when online lookups are on, the ArchWiki
            if websearch.is_technical(text):
                try:
                    tech = websearch.technical_lookup(text, settings, token=self._token,
                                                      online=websearch.mode(settings) == "on")
                except Canceled:
                    tech = []
                if tech:
                    return "sources", tech, []
            return "", [], []
        # A recent verified entry of the local reference answers at once and
        # offline: nothing is sent, and the model reads a few lines instead
        # of two web excerpts (on an N100 every token is read before the first
        # word). Older entries give way to the web, when it is on.
        try:
            fresh = [k for k in store.search_knowledge(text, limit=2, origins=("reference",))
                     if store.fresh(k.retrieved, REFERENCE_FRESH_DAYS)]
        except Exception:  # noqa: BLE001
            fresh = []
        if fresh:
            return "reference", [], fresh
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
            state = "on" if choice in ("yes", "always") else "off"
        web, sources = "off", []
        if state != "off":
            try:
                sources, _reachable = websearch.lookup(text, settings, lang=language(),
                                                       token=self._token, compact=True)
            except Canceled:
                sources = []
            web = "sources" if sources else "failed"
        if web == "sources":
            return web, sources, []
        try:
            reference = store.search_knowledge(text, limit=2, origins=("reference", "web"))
        except Exception:  # noqa: BLE001 - no reference: say it can't be verified
            reference = []
        return ("reference", [], reference) if reference else (web, [], [])

    def _not_ready(self, prov: Provider) -> str:
        """The local model can't answer at all: say why."""
        self.last_turn["error"] = "setup"
        if getattr(prov, "list_models", lambda: [])():
            from . import resources
            need = prov._model_gb() if hasattr(prov, "_model_gb") else 0.0
            return resources.memory_reason(need)
        return NOT_CONFIGURED

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

    def _close_turn(self, text: str, final: str, start: int) -> str:
        final = self._honest(final, False)
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
        say the rest is missing. No hidden second request."""
        received: list[str] = []

        def chunk(c: str) -> None:
            received.append(c)
            on_text(c)

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
            return self._error_reply(e)
        except Exception as e:  # noqa: BLE001 - a bug must not freeze the turn
            if received:
                return Reply(text="".join(received) + "\n\n" + tr("(The reply was cut off.)"))
            return Reply(text=tr("Unexpected error: {error}").format(error=e), error="error")

    def _turn(self) -> Reply:
        try:
            return self.provider.chat(self._window())
        except InsufficientMemoryError as e:
            # Typical on the live system: little memory and no swap on disk.
            # Say so plainly, instead of making the computer crawl.
            return Reply(text=str(e), error="memory")
        except Canceled:
            return Reply(error="canceled")
        except ProviderError as e:
            return self._error_reply(e)
        except Exception:  # noqa: BLE001
            if not self.provider.available():
                return Reply(text=NOT_CONFIGURED, error="setup")
            return Reply(text=tr("The local model isn't responding. Check it in Settings › AI."),
                         error="network")
