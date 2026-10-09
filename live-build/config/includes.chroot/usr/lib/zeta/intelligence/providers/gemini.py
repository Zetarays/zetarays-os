# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider Google Gemini per ZETA RAYS Intelligence (API generativelanguage, via urllib)."""
from __future__ import annotations

import json
from typing import Callable

from .base import Message, Provider, Reply, ToolSpec

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# veloce; un altro in Impostazioni › AI. Verificato il 7 ottobre 2026:
# gemini-2.5-flash resta solo per chi lo usava gia', le chiavi nuove no.
DEFAULT_MODEL = "gemini-3.8-flash"


class GeminiProvider(Provider):
    def _model(self) -> str:
        return self.config.model or DEFAULT_MODEL

    def _url(self, method: str) -> str:
        # la chiave NON va nell'indirizzo (finirebbe nei registri di proxy e
        # server): viaggia nell'intestazione x-goog-api-key, vedi _intestazioni
        return "%s/%s:%s" % (self.config.endpoint or BASE, self._model(), method)

    def _intestazioni(self) -> dict:
        return {"content-type": "application/json", "x-goog-api-key": self.config.api_key}

    def modelli_offerti(self) -> list[str]:
        import urllib.request
        req = urllib.request.Request((self.config.endpoint or BASE) + "?pageSize=200",
                                     headers=self._intestazioni())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                dati = json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - e' solo un aiuto in piu'
            return []
        return [m.get("name", "").split("/", 1)[-1] for m in dati.get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]

    def _contents(self, messages: list[Message]) -> dict:
        contents = [{"role": "user" if m.role == "user" else "model",
                     "parts": [{"text": m.content}]} for m in messages]
        payload = {"contents": contents,
                   "generationConfig": {"temperature": self.config.temperature,
                                        "maxOutputTokens": self.config.max_tokens}}
        if self.config.system:
            payload["systemInstruction"] = {"parts": [{"text": self.config.system}]}
        return payload

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> Reply:
        data = self._post(self._url("generateContent"), self._contents(messages),
                          self._intestazioni())
        reply = Reply()
        cand = (data.get("candidates") or [{}])[0]
        for part in cand.get("content", {}).get("parts", []):
            reply.text += part.get("text", "")
        usage = data.get("usageMetadata", {})
        reply.input_tokens = usage.get("promptTokenCount", 0)
        reply.output_tokens = usage.get("candidatesTokenCount", 0)
        return reply

    def stream(self, messages: list[Message],
               on_text: Callable[[str], None]) -> Reply:
        reply = Reply()
        buffer = b""
        for raw in self._post_stream(self._url("streamGenerateContent") + "?alt=sse",
                                     self._contents(messages),
                                     self._intestazioni()):
            buffer += raw
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                text = line.decode("utf-8", "replace").strip()
                if not text.startswith("data:"):
                    continue
                try:
                    ev = json.loads(text[5:].strip())
                except ValueError:
                    continue
                for cand in ev.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        chunk = part.get("text", "")
                        if chunk:
                            reply.text += chunk
                            on_text(chunk)
        return reply
