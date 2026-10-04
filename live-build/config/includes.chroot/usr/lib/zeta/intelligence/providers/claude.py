# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider Claude (Anthropic) per ZETA RAYS Intelligence.

Usa direttamente l'endpoint Messages via urllib: nessun SDK da installare.
Modello predefinito: claude-haiku-4-5 (il piu' veloce: ZETA deve rispondere
subito; un altro si sceglie in Impostazioni › AI).
"""
from __future__ import annotations

import json
from typing import Callable

from .base import Message, Provider, Reply, ToolCall, ToolSpec

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5"


class ClaudeProvider(Provider):
    def modelli_offerti(self) -> list[str]:
        import urllib.request
        req = urllib.request.Request("https://api.anthropic.com/v1/models?limit=100", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return [m.get("id", "") for m in json.loads(r.read().decode("utf-8")).get("data", [])]
        except Exception:  # noqa: BLE001 - e' solo un aiuto in piu'
            return []

    def _headers(self) -> dict:
        return {
            "content-type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": API_VERSION,
        }

    def _payload(self, messages: list[Message], tools: list[ToolSpec] | None,
                 stream: bool) -> dict:
        payload = {
            "model": self.config.model or DEFAULT_MODEL,
            "max_tokens": self.config.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if self.config.system:
            payload["system"] = self.config.system
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.schema}
                for t in tools
            ]
        if stream:
            payload["stream"] = True
        return payload

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> Reply:
        data = self._post(API_URL, self._payload(messages, tools, False), self._headers())
        reply = Reply(stop_reason=data.get("stop_reason", "end_turn"))
        for block in data.get("content", []):
            if block.get("type") == "text":
                reply.text += block.get("text", "")
            elif block.get("type") == "tool_use":
                reply.tool_calls.append(
                    ToolCall(id=block.get("id", ""), name=block.get("name", ""),
                             arguments=block.get("input", {})))
        usage = data.get("usage", {})
        reply.input_tokens = usage.get("input_tokens", 0)
        reply.output_tokens = usage.get("output_tokens", 0)
        return reply

    def stream(self, messages: list[Message],
               on_text: Callable[[str], None]) -> Reply:
        reply = Reply()
        for raw in self._post_stream(API_URL, self._payload(messages, None, True),
                                     self._headers()):
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except ValueError:
                continue
            t = ev.get("type")
            if t == "content_block_delta":
                delta = ev.get("delta", {})
                if delta.get("type") == "text_delta":
                    chunk = delta.get("text", "")
                    reply.text += chunk
                    on_text(chunk)
            elif t == "message_delta":
                reply.stop_reason = ev.get("delta", {}).get("stop_reason", reply.stop_reason)
                reply.output_tokens = ev.get("usage", {}).get("output_tokens", reply.output_tokens)
            elif t == "message_start":
                reply.input_tokens = ev.get("message", {}).get("usage", {}).get("input_tokens", 0)
        return reply
