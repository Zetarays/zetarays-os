# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider Ollama (modelli locali) per ZETA RAYS Intelligence.

ZETA RAYS funziona anche senza Internet: se Ollama è in esecuzione con un modello
compatibile, ZETA usa quello. Rileva i modelli installati.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from i18n import tr

from .base import Message, Provider, Reply, ToolSpec
from .. import risorse

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"


class MemoriaInsufficiente(RuntimeError):
    """Non c'è memoria per caricare il modello: meglio dirlo che bloccarsi."""


class OllamaProvider(Provider):
    # Il modello locale non riceve le azioni (i comandi li riconosce ZETA da
    # solo, in intents.py): le sue risposte vanno sempre in streaming.
    usa_strumenti = False

    def _base(self) -> str:
        return (self.config.endpoint or DEFAULT_ENDPOINT).rstrip("/")

    def available(self) -> bool:
        """Utilizzabile solo se Ollama risponde E c'è memoria per il modello.

        Dichiararsi disponibile senza avere la memoria per caricare il modello
        significa far scegliere questo provider e poi piantare il computer nel
        momento in cui l'utente fa la prima domanda.
        """
        if not risorse.memoria_per_il_modello() and not self._gia_caricato():
            return False
        return bool(self.list_models())

    def test(self, timeout: float = 25.0) -> tuple[bool, str]:
        """Prova il collegamento locale senza far caricare il modello.

        La prova comune fa una domanda vera: per Ollama significherebbe tirare
        su il modello, che su una macchina modesta prende decine di secondi e
        farebbe scadere la prova facendola sembrare un guasto. Qui si guarda
        cio' che conta: il servizio risponde, il modello c'e', la memoria basta.
        """
        modelli = self.list_models()
        if not modelli:
            return False, tr("Ollama isn't responding at {address}. Check that the service "
                             "is running: systemctl status ollama").format(address=self._base())
        voluto = self._model()
        if voluto and voluto not in modelli:
            return False, tr("The model “{model}” isn't installed. Available: {models}.").format(
                model=voluto, models=", ".join(modelli))
        if self._gia_caricato():
            return True, tr("Connected, model {model} already in memory (instant replies).").format(
                model=voluto)
        if not risorse.memoria_per_il_modello():
            return False, tr("Ollama is responding, but there isn't enough free memory to "
                             "load the model: questions would hang.")
        return True, tr("Connected, model {model} ready. The first reply needs to "
                        "load it into memory.").format(model=voluto)

    def _gia_caricato(self) -> bool:
        """Il modello è già in memoria: usarlo non costa altra memoria."""
        try:
            with urllib.request.urlopen(self._base() + "/api/ps", timeout=2.0) as resp:
                dati = json.loads(resp.read().decode("utf-8"))
            return bool(dati.get("models"))
        except (urllib.error.URLError, ValueError, OSError):
            return False

    def preload(self) -> bool:
        """Carica il modello in memoria senza generare nulla.

        Serve a togliere l'attesa del primo utilizzo: a freddo il modello ci
        mette decine di secondi a salire, poi risponde in frazioni di secondo.
        """
        if not risorse.memoria_per_il_modello():
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
        """Modelli installati localmente (vuoto se Ollama non è in esecuzione)."""
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
        # un modello locale piccolo con molta cronologia perde il filo e
        # risponde alle domande vecchie: bastano gli ultimi scambi
        recenti = messages[-self.MAX_CRONOLOGIA:]
        while recenti and recenti[0].role != "user":
            recenti = recenti[1:]
        out.extend({"role": m.role, "content": m.content} for m in recenti)
        return out

    MAX_CRONOLOGIA = 8

    # Risposte brevi: con un modello piccolo una risposta lunga è quasi sempre
    # divagante e fa aspettare l'utente per nulla.
    MAX_TOKEN = 220

    @property
    def KEEP_ALIVE(self) -> str:          # noqa: N802  (nome storico)
        """Quanto il modello resta in memoria dopo l'ultima domanda.

        Non è una costante: dipende da quanta RAM ha il computer. Tenere 1,8 GB
        occupati per mezz'ora su una macchina da 4 GB è la ricetta esatta per i
        blocchi e le lentezze che si vogliono evitare.
        """
        return risorse.keep_alive()

    def _options(self) -> dict:
        opz = {"temperature": self.config.temperature,
               "num_predict": self.config.max_tokens or self.MAX_TOKEN}
        if self.config.context:
            opz["num_ctx"] = self.config.context
        return opz

    def _controlla_memoria(self) -> None:
        if not self._gia_caricato() and not risorse.memoria_per_il_modello():
            raise MemoriaInsufficiente(risorse.motivo_memoria())

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> Reply:
        self._controlla_memoria()
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
        self._controlla_memoria()
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
