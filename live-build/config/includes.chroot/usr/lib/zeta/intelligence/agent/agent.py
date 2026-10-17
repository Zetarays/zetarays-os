# SPDX-License-Identifier: GPL-3.0-or-later
"""The ZETA Core chain: request -> understand -> action -> verify -> reply.

  1. understand locally (understanding.py): milliseconds, no network;
  2. if that is not enough, the model picks ONE action from the catalog (JSON
     answer constrained to the capability names); the arguments it picks
     must appear in the request (no invented names);
  3. "confirm" actions ask for permission first;
  4. the reply is the verification's result, never a courtesy "done".
Every action is logged in ~/.local/share/zeta/actions.log (passwords are not).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from i18n import tr
from i18n_data import load

from . import capabilities as C
from . import state as S

LOG = os.path.expanduser("~/.local/share/zeta/actions.log")
SECRETS = {"password", "psk", "key", "token"}


@dataclass
class ConfirmationRequest:
    """What is shown when confirmation is needed (the same fields as before:
    the ZETA window and the terminal already know how to display them)."""
    preview: str
    impact: str
    ok: bool = True
    output: str = ""
    needs_confirmation: bool = True


def _log_call(name, args, outcome, origin):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        safe_args = {k: ("***" if k in SECRETS and v else v) for k, v in (args or {}).items()}
        if os.path.exists(LOG) and os.path.getsize(LOG) > 1_000_000:
            os.replace(LOG, LOG + ".1")          # keep the log short
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "action": name, "args": safe_args,
                                "ok": outcome.ok, "outcome": outcome.message[:300], "origin": origin},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def execute(name, args, confirm=None, origin="local", authorized=False) -> C.Outcome:
    cap = C.REGISTRY.get(name)
    if cap is None:
        return C.Outcome(False, tr("I don't know how to do “{action}”.").format(action=name))
    args = {k: v for k, v in (args or {}).items() if v is not None and v != ""}
    missing = [p for p in cap.required if not args.get(p)]
    if missing:
        return C.Outcome(False, tr("I'm missing some information: {what}.").format(
            what=", ".join(C.label(p) for p in missing)))
    if cap.check:
        es = cap.check(args)
        if es is not None:
            _log_call(name, args, es, origin)
            return es
    if cap.risk == "confirm" and not authorized:
        text = cap.preview(args) if cap.preview else cap.description
        r = ConfirmationRequest(preview=text, impact=tr("Your confirmation is needed."))
        if not (confirm and confirm(r)):
            es = C.Outcome(False, tr("Canceled: nothing was done."))
            _log_call(name, args, es, origin)
            return es
    try:
        es = cap.execute(args)
    except Exception as e:  # noqa: BLE001 - an action must never bring ZETA down
        es = C.Outcome(False, tr("Error during “{action}”: {error}").format(action=name, error=e))
    _log_call(name, args, es, origin)
    return es


def run_all(actions, confirm=None, origin="local") -> str:
    answers = []
    for name, args in actions:
        es = execute(name, args, confirm, origin)
        answers.append(es.message)
        if not es.ok and len(actions) > 1:
            answers.append(tr("Stopping here: I didn't do the remaining actions."))
            break
    return "\n".join(answers)


# ------------------------------------------------------------ the model chooses
def _catalog(names=None):
    lines = []
    for c in C.REGISTRY.values():
        if names is not None and c.name not in names:
            continue
        par = ", ".join("%s%s" % (k, "" if k in c.required else "?") for k in c.parameters)
        lines.append("%s(%s): %s" % (c.name, par, c.description))
    return "\n".join(lines)


INSTRUCTIONS = (
    "You are the command engine of an operating system. Read the user's request (it may be in any "
    "language) and choose ONE action from the list, with its arguments taken from the user's words. "
    "Copy argument values exactly as the user wrote them, in the user's language: do not translate them. "
    "If the request does not ask to do something on the computer (a question, a conversation, a text "
    "to write), choose \"none\". Never invent file, app or network names the user did not say.\n"
    "Answer only with JSON: {\"action\": \"name\", \"arguments\": {...}}\n\nActions:\n")


# Words that must appear in the request for the model to be allowed to pick
# that action. The local model is small: on its own it picked "screenshot"
# for any sentence (tested). An action with no words here cannot be chosen by
# the model: only local understanding can trigger it.
# Italian and English: the request may arrive in either language. The table
# (capability -> regex alternatives) is language data: i18n-data/agent.json.
WORDS = load("agent")["words"]


def _plausible(name: str, text: str) -> bool:
    import re
    p = WORDS.get(name)
    return bool(p and re.search(r"\b(?:%s)" % p, S.norm(text)))


def _grounded(value: str, text: str) -> bool:
    """An argument chosen by the model must come from the request."""
    v = [w for w in S.norm(str(value)).replace(".", " ").split() if len(w) > 1]
    t = S.norm(text)
    if not v:
        return True
    present = sum(1 for w in v if w in t)
    return present / len(v) >= 0.6


def choose_with_model(text: str, provider) -> list | None:
    """Local model (Ollama) only: JSON answer constrained to the names."""
    try:
        from ..providers.ollama import OllamaProvider
    except ImportError:
        return None
    if not isinstance(provider, OllamaProvider) or not provider.available():
        return None
    import urllib.request
    # only the actions the sentence talks about: if there are none, just
    # chat, without waiting on a pointless choice
    candidates = [n for n in C.REGISTRY if _plausible(n, text)]
    if not candidates:
        return None
    names = candidates + ["none"]
    schema = {"type": "object", "properties": {"action": {"type": "string", "enum": names},
                                                "arguments": {"type": "object"}},
              "required": ["action"]}
    body = {"model": provider._model(), "stream": False, "format": schema,
             "keep_alive": provider.KEEP_ALIVE,
             # same load options as the chat: otherwise Ollama reloads the model
             "options": {"temperature": 0, "num_predict": 120, **provider.load_options()},
             "messages": [{"role": "system", "content": INSTRUCTIONS + _catalog(candidates)},
                          {"role": "user", "content": text}]}
    try:
        req = urllib.request.Request(provider._base() + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json"})
        # cancelable (Stop in the ZETA window closes this connection too)
        from ..providers.base import open_url
        with open_url(req, read_timeout=45, token=provider.cancel_token) as r:
            answer = json.loads(r.read(256 * 1024).decode()).get("message", {}).get("content", "")
        choice = json.loads(answer)
    except Exception:  # noqa: BLE001 - if the model does not answer, fall back to chatting
        return None
    name = choice.get("action")
    args = choice.get("arguments") or {}
    if name not in C.REGISTRY or not isinstance(args, dict) or not _plausible(name, text):
        return None
    cap = C.REGISTRY[name]
    args = {k: v for k, v in args.items() if k in cap.parameters}
    for k, v in args.items():
        if isinstance(v, str) and k not in ("text",) and not _grounded(v, text):
            return None              # invented name: better to ask than to get it wrong
    if any(not args.get(p) for p in cap.required):
        return None
    return [(name, args)]


# ------------------------------------------------------------ for online services (tool calling)
class AgentEngine:
    """The capabilities as "tools" for models that can call them (Claude,
    OpenAI, Gemini...). Same interface as the old engine."""

    def tool_specs(self):
        from ..providers.base import ToolSpec
        out = []
        for c in C.REGISTRY.values():
            props = {k: {"type": "string", "description": d} for k, d in c.parameters.items()}
            out.append(ToolSpec(name=c.name, description=c.description,
                                schema={"type": "object", "properties": props, "required": c.required}))
        return out

    def run(self, name, args, *, authorized=False):
        from ..actions import ActionResult
        cap = C.REGISTRY.get(name)
        if cap is None:
            return ActionResult(False, tr("Unknown action: {name}").format(name=name))
        args = {k: v for k, v in (args or {}).items() if v is not None and v != ""}
        if cap.check and not authorized:
            es = cap.check(args)
            if es is not None:
                return ActionResult(es.ok, es.message)
        if cap.risk == "confirm" and not authorized:
            text = cap.preview(args) if cap.preview else cap.description
            return ActionResult(True, "", needs_confirmation=True, preview=text,
                                impact=tr("Your confirmation is needed."))
        es = execute(name, args, None, origin="tools", authorized=True)
        return ActionResult(es.ok, es.message)
