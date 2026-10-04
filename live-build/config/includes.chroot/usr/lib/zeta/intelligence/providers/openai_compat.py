# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider compatibili con l'API OpenAI (chat/completions) per ZETA RAYS Intelligence.

Un solo codice copre OpenAI, DeepSeek, Qwen, Perplexity, Mistral, Groq, xAI,
OpenRouter e qualsiasi servizio compatibile (anche locale: LM Studio, vLLM,
llama.cpp server): cambiano solo endpoint, modello e chiave. Nessun SDK:
chiamata via urllib.

I nomi dei modelli cambiano spesso: quelli qui sono solo il punto di partenza
e si cambiano in Impostazioni › AI. Se un modello non esiste piu', la prova
di collegamento elenca quelli che il servizio offre davvero.
"""
from __future__ import annotations

import json
from typing import Callable

import urllib.parse
import urllib.request

from .base import Message, Provider, ProviderError, Reply, ToolCall, ToolSpec

PRESETS = {
    "openai":     ("OpenAI",     "https://api.openai.com/v1/chat/completions",   "gpt-5-mini"),
    "deepseek":   ("DeepSeek",   "https://api.deepseek.com/v1/chat/completions", "deepseek-chat"),
    "qwen":       ("Qwen",       "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus"),
    # Perplexity: risponde cercando sul web, con le fonti
    "perplexity": ("Perplexity", "https://api.perplexity.ai/chat/completions",   "sonar"),
    "mistral":    ("Mistral",    "https://api.mistral.ai/v1/chat/completions",   "mistral-small-latest"),
    "groq":       ("Groq",       "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile"),
    # xAI: l'interfaccia chat/completions e' quella compatibile («legacy» per xAI)
    "xai":        ("xAI Grok",   "https://api.x.ai/v1/chat/completions",         "grok-4.7"),
    # OpenRouter: una chiave sola per molti modelli; «auto» sceglie da se'
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1/chat/completions", "openrouter/auto"),
    # qualsiasi servizio compatibile: indirizzo e modello li scrive l'utente
    "personalizzato": ("Personalizzato", "", ""),
}

# Servizi a cui NON si inviano le azioni di ZETA (function calling): a loro
# si scrive senza, e la risposta arriva in streaming.
#  - perplexity: non le accetta;
#  - personalizzato: di solito e' un modello locale piccolo. Provato con
#    llama3.2:1b: con le 52 azioni allegate rispondeva a «dimmi ciao» con una
#    chiamata di funzione in formato grezzo, dopo 11 s invece di 0,2 s. I
#    comandi li riconosce gia' ZETA da solo (intents.py), prima del modello.
SENZA_STRUMENTI = {"perplexity", "personalizzato"}

# Servizi che possono girare sul computer stesso, senza chiave
_HOST_LOCALI = ("localhost", "127.0.0.1", "::1")


class OpenAICompatProvider(Provider):
    # Un servizio che rifiuta le azioni lo si scopre alla prima risposta: da
    # li' in poi, per quel servizio, si scrive senza (vale per la sessione).
    _rifiuta_strumenti: set[str] = set()

    @property
    def usa_strumenti(self) -> bool:          # type: ignore[override]
        n = self.config.name
        return n not in SENZA_STRUMENTI and n not in self._rifiuta_strumenti

    def _locale(self) -> bool:
        host = urllib.parse.urlparse(self._url()).hostname or ""
        return host in _HOST_LOCALI or host.endswith(".local")

    def available(self) -> bool:
        if not self._url() or not self._model():
            return False
        return bool(self.config.api_key) or self._locale()

    def _url(self) -> str:
        return self.config.endpoint or PRESETS.get(self.config.name, ("", "", ""))[1]

    def _model(self) -> str:
        return self.config.model or PRESETS.get(self.config.name, ("", "", ""))[2]

    def _headers(self) -> dict:
        h = {"content-type": "application/json"}
        if self.config.api_key:           # i servizi locali spesso non la vogliono
            h["authorization"] = "Bearer %s" % self.config.api_key
        return h

    def _messages(self, messages: list[Message]) -> list[dict]:
        out = []
        if self.config.system:
            out.append({"role": "system", "content": self.config.system})
        out.extend({"role": m.role, "content": m.content} for m in messages)
        return out

    def _tools(self, tools: list[ToolSpec] | None) -> list[dict] | None:
        if not tools:
            return None
        return [{"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.schema}} for t in tools]

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> Reply:
        payload = {
            "model": self._model(),
            "messages": self._messages(messages),
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        tool_defs = self._tools(tools) if self.usa_strumenti else None
        if tool_defs:
            payload["tools"] = tool_defs
        try:
            data = self._post(self._url(), payload, self._headers())
        except ProviderError as e:
            # Molti servizi compatibili non accettano le azioni e rispondono
            # 400/422: si riprova una volta senza, invece di fallire.
            if not tool_defs or e.status not in (400, 404, 422):
                raise
            self._rifiuta_strumenti.add(self.config.name)
            payload.pop("tools", None)
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
        payload = {
            "model": self._model(),
            "messages": self._messages(messages),
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": True,
        }
        reply = Reply()
        for raw in self._post_stream(self._url(), payload, self._headers()):
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

    # --- prova di collegamento ---
    def modelli_offerti(self) -> list[str]:
        return self._modelli_offerti()

    def _modelli_offerti(self) -> list[str]:
        """I modelli che il servizio offre davvero (GET .../models)."""
        base = self._url().rsplit("/chat/completions", 1)[0]
        req = urllib.request.Request(base + "/models", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - e' solo un aiuto in piu'
            return []
        voci = data.get("data") if isinstance(data, dict) else data
        return sorted({v.get("id", "") for v in voci or [] if isinstance(v, dict)} - {""})

    def test(self, timeout: float = 25.0) -> tuple[bool, str]:
        if not self._url():
            return False, "Manca l'indirizzo del servizio (endpoint)."
        if not self._model():
            return False, "Manca il nome del modello."
        if not self.config.api_key and not self._locale():
            return False, "Manca la chiave API."
        ok, msg = super().test(timeout) if self.config.api_key else self._prova_locale(timeout)
        if not ok and any(k in msg.lower() for k in ("model", "modello", "404", "not found")):
            offerti = self._modelli_offerti()
            if offerti:
                elenco = ", ".join(offerti[:12]) + ("…" if len(offerti) > 12 else "")
                msg += " Modelli disponibili: %s" % elenco
        return ok, msg

    def _prova_locale(self, timeout: float) -> tuple[bool, str]:
        """Come la prova normale, ma per un servizio locale senza chiave (la
        prova della classe base si ferma subito se la chiave manca)."""
        prec_tokens, prec_timeout = self.config.max_tokens, self.timeout
        self.config.max_tokens, self.timeout = 16, timeout
        try:
            self.chat([Message(role="user", content="ok")])
            return True, "Collegato (modello %s)." % self._model()
        except ProviderError as e:
            return False, str(e)
        finally:
            self.config.max_tokens, self.timeout = prec_tokens, prec_timeout
