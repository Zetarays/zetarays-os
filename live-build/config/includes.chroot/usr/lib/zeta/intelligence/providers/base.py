# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — interfaccia comune dei provider AI.

Ogni provider (Claude, Gemini, OpenAI, DeepSeek, Qwen, Ollama) espone la
stessa interfaccia, così ZETA non deve conoscere i dettagli di ognuno.
Nessuna dipendenza esterna: solo urllib della libreria standard.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterator


class ProviderError(Exception):
    """Errore di un provider, con un messaggio già comprensibile all'utente."""

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
    """Descrizione di uno strumento (azione) che l'AI può richiedere."""
    name: str
    description: str
    schema: dict         # JSON schema dei parametri


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    """Risposta di un provider a un giro di conversazione."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"    # end_turn | tool_use | refusal | max_tokens


@dataclass
class ProviderConfig:
    name: str                        # id interno (claude, gemini, ...)
    label: str                       # nome mostrato all'utente
    kind: str                        # "cloud" | "local"
    model: str = ""
    endpoint: str = ""
    api_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    system: str = ""
    timeout: float = 0.0             # secondi; 0 = valore normale (120 s, 300 s in streaming)
    stream: bool = True              # risposta che compare mentre viene scritta
    context: int = 0                 # finestra di contesto (solo modelli locali); 0 = del modello


class Provider:
    """Base di ogni provider. `chat` esegue un giro; `stream` uno in streaming."""

    # Il fornitore sa usare le azioni di ZETA (tool calling)? Chi non le usa
    # puo' rispondere subito in streaming: la risposta compare mentre viene
    # scritta, invece che tutta insieme alla fine.
    usa_strumenti = True

    def __init__(self, config: ProviderConfig):
        self.config = config
        # Tempo massimo di attesa, quando serve accorciarlo rispetto al
        # normale: la prova di connessione non puo' tenere ferma una finestra
        # per due minuti se la rete non risponde.
        self.timeout: float | None = None

    # --- API pubblica ---
    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> Reply:
        raise NotImplementedError

    def stream(self, messages: list[Message],
               on_text: Callable[[str], None]) -> Reply:
        """Streaming di solo testo. I provider senza streaming ricadono su chat."""
        reply = self.chat(messages)
        if reply.text:
            on_text(reply.text)
        return reply

    def modelli_offerti(self) -> list[str]:
        """I modelli che il servizio offre davvero (per il ripiego automatico).
        Ogni fornitore che lo sa fare lo ridefinisce; [] = non si sa."""
        return []

    def available(self) -> bool:
        """True se il provider è configurato e utilizzabile."""
        if self.config.kind == "cloud":
            return bool(self.config.api_key)
        return True

    def test(self, timeout: float = 25.0) -> tuple[bool, str]:
        """Prova davvero il collegamento e dice com'e' andata, in italiano.

        Non basta guardare se c'e' una chiave: una chiave scaduta, un modello
        che non esiste piu' o una rete che non esce danno tutti lo stesso
        aspetto («configurato») finche' non si prova. Qui si fa la richiesta
        piu' piccola possibile e si riporta l'esito vero.
        """
        if self.config.kind == "cloud" and not self.config.api_key:
            return False, "Manca la chiave API."
        prec_tokens, prec_timeout = self.config.max_tokens, self.timeout
        self.config.max_tokens, self.timeout = 16, timeout
        try:
            self.chat([Message(role="user", content="ok")])
            return True, "Collegato (modello %s)." % (self.config.model or "predefinito")
        except ProviderError as e:
            return False, str(e)
        except NotImplementedError:
            return False, "Questo provider non è ancora utilizzabile."
        except Exception as e:  # noqa: BLE001 - la prova non deve mai far cadere l'interfaccia
            return False, "Errore inatteso: %s" % e
        finally:
            self.config.max_tokens, self.timeout = prec_tokens, prec_timeout

    # --- Utilità comuni ---
    def _non_raggiungibile(self, motivo) -> "ProviderError":
        """Motivi di rete in italiano (prima arrivava «timed out», «Name or
        service not known»...)."""
        m = str(motivo).lower()
        if "timed out" in m or "timeout" in m:
            spiega = "non ha risposto in tempo"
        elif "name or service" in m or "temporary failure in name resolution" in m or "nodename" in m:
            spiega = "nessuna connessione a internet, o il DNS non risponde"
        elif "refused" in m:
            spiega = "connessione rifiutata"
        elif "unreachable" in m:
            spiega = "rete non raggiungibile"
        else:
            spiega = str(motivo)
        return ProviderError("Impossibile contattare %s: %s." % (self.config.label, spiega), retryable=True)

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
            raise self._non_raggiungibile(e.reason) from None
        except (TimeoutError, OSError) as e:
            # il servizio ha smesso di rispondere a meta' (lettura scaduta)
            raise self._non_raggiungibile(e) from None

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
            raise self._non_raggiungibile(e.reason) from None
        except (TimeoutError, OSError) as e:
            # il servizio ha smesso di rispondere a meta' (lettura scaduta)
            raise self._non_raggiungibile(e) from None
        try:
            for raw in resp:
                yield raw
        except (TimeoutError, OSError) as e:
            raise self._non_raggiungibile(e) from None

    def _error_message(self, code: int, body: str) -> str:
        detail = ""
        try:
            j = json.loads(body)
            detail = (j.get("error", {}) or {}).get("message", "") if isinstance(j.get("error"), dict) else str(j.get("error", ""))
        except (ValueError, AttributeError):
            detail = body[:200]
        if code == 401 or (code == 400 and "api key" in detail.lower()):
            # Gemini risponde 400 «API key not valid» invece di 401
            return "%s: chiave API non valida o assente." % self.config.label
        if code == 403:
            return "%s: accesso negato dalla chiave API." % self.config.label
        if code == 404:
            return "%s: modello o endpoint non trovato (%s)." % (self.config.label, self.config.model)
        if code == 429:
            return "%s: troppe richieste, riprova tra poco." % self.config.label
        if code >= 500:
            return "%s: errore del servizio, riprova più tardi." % self.config.label
        return "%s: %s" % (self.config.label, detail or ("errore %d" % code))


# Modelli preferiti quando il predefinito non esiste piu' (i nomi cambiano nel
# tempo): prima quelli veloci. Si confrontano come parti del nome.
PREFERITI = {
    "claude": ["claude-haiku-4-5", "claude-sonnet-5", "haiku", "sonnet"],
    "gemini": ["gemini-2.5-flash", "flash", "gemini"],
    "openai": ["gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4o-mini"],
    "deepseek": ["deepseek-chat"],
    "qwen": ["qwen-plus", "qwen-flash", "qwen-turbo", "qwen-max"],
    "perplexity": ["sonar"],
    "mistral": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest", "mistral"],
    "groq": ["llama-3.3-70b", "llama", "gpt-oss", "qwen"],
    "xai": ["grok-4", "grok"],
    "openrouter": ["openrouter/auto"],
}
_NON_CHAT = ("embed", "image", "tts", "audio", "whisper", "moderation", "guard", "realtime",
             "transcribe", "vision-preview", "search-preview", "dall-e", "veo", "imagen", "live")


def scegli_modello(provider_id: str, offerti: list[str]) -> str:
    """Il modello di chat da usare fra quelli offerti, secondo PREFERITI."""
    chat = [m for m in offerti if m and not any(x in m.lower() for x in _NON_CHAT)]
    for parte in PREFERITI.get(provider_id, []):
        trovati = sorted((m for m in chat if parte in m.lower()), reverse=True)
        # a parita' si preferisce il nome senza data (alias che segue gli aggiornamenti)
        trovati.sort(key=lambda m: (not m.lower().startswith(parte), len(m)))
        if trovati:
            return trovati[0]
    return chat[0] if chat else ""
