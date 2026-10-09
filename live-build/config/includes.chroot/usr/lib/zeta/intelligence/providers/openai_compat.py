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
import re
from typing import Callable, Iterator

import urllib.parse
import urllib.request

from i18n import tr

from .base import Message, Provider, ProviderError, Reply, ToolCall, ToolSpec

# Modelli predefiniti verificati sulla documentazione dei servizi il 7 ottobre
# 2026: i veloci ed economici, adatti a un assistente. Se uno sparisce, ZETA
# ne sceglie da solo un altro fra quelli offerti (assistant.py).
PRESETS = {
    "openai":     ("OpenAI",     "https://api.openai.com/v1/chat/completions",   "gpt-6-luna"),
    "deepseek":   ("DeepSeek",   "https://api.deepseek.com/v1/chat/completions", "deepseek-flash"),
    "qwen":       ("Qwen",       "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen3.8-flash"),
    # Perplexity: risponde cercando sul web, con le fonti
    "perplexity": ("Perplexity", "https://api.perplexity.ai/chat/completions",   "sonar"),
    "mistral":    ("Mistral",    "https://api.mistral.ai/v1/chat/completions",   "mistral-small-latest"),
    "groq":       ("Groq",       "https://api.groq.com/openai/v1/chat/completions", "openai/gpt-oss-20b"),
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

# I modelli «che ragionano» di OpenAI (gpt-5 e successivi, serie o) rifiutano
# max_tokens (vogliono max_completion_tokens) e una temperatura diversa da
# quella di fabbrica: con questi due campi ZETA riceveva solo un errore 400.
_OPENAI_RAGIONA = re.compile(r"^(gpt-[5-9]|o[1-9])")


def _sforzo(model: str) -> str:
    """Sforzo di ragionamento minimo: un assistente deve rispondere subito.
    I primi gpt-5 conoscono «minimal»; dai gpt-5.1 in poi c'e' «none», e sulle
    Chat Completions i gpt-6 usano le azioni solo con «none». Serie o: il loro."""
    breve = model.split("-20", 1)[0]                # senza la data della versione
    if breve in ("gpt-5", "gpt-5-mini", "gpt-5-nano"):
        return "minimal"
    return "none" if breve.startswith("gpt-") else ""

# Servizi che possono girare sul computer stesso, senza chiave
_HOST_LOCALI = ("localhost", "127.0.0.1", "::1")


class OpenAICompatProvider(Provider):
    # Un servizio che rifiuta le azioni lo si scopre alla prima risposta: da
    # li' in poi, per quel servizio, si scrive senza (vale per la sessione).
    _rifiuta_strumenti: set[str] = set()
    # Campi che un servizio ha rifiutato (per servizio e modello): imparati
    # dalla prima risposta 400, non si rimandano piu' nella sessione.
    _adattamenti: dict[tuple[str, str], set[str]] = {}

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

    def _base(self, messages: list[Message]) -> dict:
        """La richiesta comune a chat e stream, nella forma che il servizio
        e il modello accettano."""
        model = self._model()
        payload = {"model": model, "messages": self._messages(messages),
                   "max_tokens": self.config.max_tokens,
                   "temperature": self.config.temperature}
        if self.config.name == "openai" and _OPENAI_RAGIONA.match(model):
            payload["max_completion_tokens"] = payload.pop("max_tokens")
            payload.pop("temperature")
            if _sforzo(model):
                payload["reasoning_effort"] = _sforzo(model)
        for campo in self._adattamenti.get((self.config.name, model), ()):
            self._togli(payload, campo)
        return payload

    @staticmethod
    def _togli(payload: dict, campo: str) -> None:
        if campo == "max_tokens" and "max_tokens" in payload:
            payload["max_completion_tokens"] = payload.pop("max_tokens")
        else:
            payload.pop(campo, None)

    def _adatta(self, payload: dict, e: ProviderError) -> bool:
        """Un 400 che nomina un campo della richiesta («Unsupported parameter:
        'max_tokens'», «temperature does not support 0.7»): lo si toglie e si
        riprova. Vero se la richiesta e' cambiata."""
        if e.status not in (400, 422):
            return False
        msg = str(e).lower()
        for campo in ("max_tokens", "temperature", "reasoning_effort"):
            if campo in payload and campo in msg:
                self._togli(payload, campo)
                self._adattamenti.setdefault((self.config.name, payload["model"]), set()).add(campo)
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
        tool_defs = self._tools(tools) if self.usa_strumenti else None
        if tool_defs:
            payload["tools"] = tool_defs
        for _tentativo in range(4):
            try:
                data = self._post(self._url(), payload, self._headers())
                break
            except ProviderError as e:
                if self._adatta(payload, e):
                    continue
                # Molti servizi compatibili non accettano le azioni e rispondono
                # 400/422: si riprova senza, invece di fallire.
                if "tools" not in payload or e.status not in (400, 404, 422):
                    raise
                self._rifiuta_strumenti.add(self.config.name)
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
        for raw in self._righe_stream(payload):
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

    def _righe_stream(self, payload: dict) -> Iterator[bytes]:
        """Le righe della risposta in streaming; se il servizio rifiuta un campo
        prima di cominciare, lo si toglie e si riprova (come in chat)."""
        for _tentativo in range(3):
            righe = self._post_stream(self._url(), payload, self._headers())
            try:
                prima = next(righe)
            except StopIteration:
                return
            except ProviderError as e:
                if self._adatta(payload, e):
                    continue
                raise
            yield prima
            yield from righe
            return
        yield from self._post_stream(self._url(), payload, self._headers())

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
            return False, tr("The service address (endpoint) is missing.")
        if not self._model():
            return False, tr("The model name is missing.")
        if not self.config.api_key and not self._locale():
            return False, tr("The API key is missing.")
        ok, msg = super().test(timeout) if self.config.api_key else self._prova_locale(timeout)
        if not ok and any(k in msg.lower() for k in ("model", "modello", "404", "not found")):
            offerti = self._modelli_offerti()
            if offerti:
                elenco = ", ".join(offerti[:12]) + ("…" if len(offerti) > 12 else "")
                msg += " " + tr("Available models: {models}").format(models=elenco)
        return ok, msg

    def _prova_locale(self, timeout: float) -> tuple[bool, str]:
        """Come la prova normale, ma per un servizio locale senza chiave (la
        prova della classe base si ferma subito se la chiave manca)."""
        prec_tokens, prec_timeout = self.config.max_tokens, self.timeout
        self.config.max_tokens, self.timeout = 16, timeout
        try:
            self.chat([Message(role="user", content="ok")])
            return True, tr("Connected (model {model}).").format(model=self._model())
        except ProviderError as e:
            return False, str(e)
        finally:
            self.config.max_tokens, self.timeout = prec_tokens, prec_timeout
