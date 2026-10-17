# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — common interface for AI providers.

Every provider (Claude, Gemini, OpenAI, DeepSeek, Qwen, Ollama) exposes the
same interface, so ZETA does not need to know the details of each one.
No external dependencies: only urllib from the standard library.
"""
from __future__ import annotations

import email.utils
import errno
import functools
import http.client
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterator

from i18n import tr


class ProviderError(Exception):
    """A provider error, carrying a message that is already user-readable.

    `kind` is a stable key (never shown, never translated) that the assistant
    and the tests use: auth, quota, rate_limit, model, too_long, server,
    bad_request, network, timeout, canceled, empty, error.
    """

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None,
                 kind: str = "error", retry_after: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.kind = kind
        self.retry_after = retry_after


class Canceled(ProviderError):
    """The user stopped the request (or a newer request replaced it)."""

    def __init__(self, message: str = ""):
        super().__init__(message or tr("Request canceled."), kind="canceled")


# --- time limits -----------------------------------------------------------
# Every request has three limits, so that nothing can leave ZETA waiting
# forever: reaching the server, the first piece of the reply, the whole reply.
# A local model on a modest computer needs longer to start (it may have to be
# loaded into memory) than an online service.
CONNECT_TIMEOUT = 10.0
FIRST_TOKEN_TIMEOUT = {"local": 60.0, "cloud": 30.0}
# without streaming the server answers only when the whole reply is ready
WHOLE_REPLY_TIMEOUT = {"local": 120.0, "cloud": 90.0}
TOTAL_TIMEOUT = {"local": 300.0, "cloud": 180.0}
MAX_REPLY_BYTES = 8 * 1024 * 1024        # a non-streamed reply larger than this is not read


class CancelToken:
    """Lets another thread abort a request that is blocked on the network.

    Closing the socket (shutdown) wakes up the thread blocked in recv(), which
    then fails at once: the HTTP stream really stops, instead of being only
    ignored while it keeps running in the background.
    Tokens form a tree: canceling a conversation turn cancels each of its
    requests; a request's own deadline cancels only that request.
    """

    def __init__(self, parent: "CancelToken | None" = None):
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._socks: set = set()
        self._children: set = set()
        self.reason = ""
        self._parent = parent
        if parent is not None:
            parent._adopt(self)

    @property
    def canceled(self) -> bool:
        return self._event.is_set()

    def cancel(self, reason: str = "canceled") -> None:
        with self._lock:
            if self._event.is_set():
                return
            self.reason = reason
            self._event.set()
            socks, children = list(self._socks), list(self._children)
        for s in socks:
            _shutdown(s)
        for c in children:
            c.cancel(reason)

    def child(self) -> "CancelToken":
        return CancelToken(self)

    def close(self) -> None:
        """The request is over: forget it (the tree must not grow forever)."""
        if self._parent is not None:
            with self._parent._lock:
                self._parent._children.discard(self)
        with self._lock:
            self._socks.clear()

    def wait(self, seconds: float) -> bool:
        return self._event.wait(seconds)

    def _adopt(self, child: "CancelToken") -> None:
        with self._lock:
            if not self._event.is_set():
                self._children.add(child)
                return
        child.cancel(self.reason)

    def register(self, sock) -> None:
        with self._lock:
            if not self._event.is_set():
                self._socks.add(sock)
                return
        _shutdown(sock)

    def unregister(self, sock) -> None:
        with self._lock:
            self._socks.discard(sock)


def _shutdown(sock) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


class _TimedHTTPConnection(http.client.HTTPConnection):
    """Connects within CONNECT_TIMEOUT, then waits for data with its own
    (longer) read timeout; the socket is handed to the cancel token."""

    def __init__(self, *args, read_timeout: float = 60.0, token: CancelToken | None = None, **kw):
        super().__init__(*args, **kw)
        self._read_timeout = read_timeout
        self._token = token

    def connect(self):
        super().connect()
        self.sock.settimeout(self._read_timeout)
        if self._token is not None:
            self._token.register(self.sock)


class _TimedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, read_timeout: float = 60.0, token: CancelToken | None = None, **kw):
        super().__init__(*args, **kw)
        self._read_timeout = read_timeout
        self._token = token

    def connect(self):
        super().connect()
        self.sock.settimeout(self._read_timeout)
        if self._token is not None:
            self._token.register(self.sock)


class _TimedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, read_timeout, token):
        super().__init__()
        self._kw = {"read_timeout": read_timeout, "token": token}

    def http_open(self, req):
        return self.do_open(functools.partial(_TimedHTTPConnection, **self._kw), req)


class _TimedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, read_timeout, token):
        super().__init__()
        self._kw = {"read_timeout": read_timeout, "token": token}

    def https_open(self, req):
        return self.do_open(functools.partial(_TimedHTTPSConnection, **self._kw), req,
                            context=self._context)


def open_url(req: urllib.request.Request, *, read_timeout: float,
             token: CancelToken | None = None):
    """urlopen with a connect timeout, a read timeout and cancellation.
    No cookie handler: nothing is stored between requests."""
    opener = urllib.request.build_opener(_TimedHTTPHandler(read_timeout, token),
                                         _TimedHTTPSHandler(read_timeout, token))
    return opener.open(req, timeout=CONNECT_TIMEOUT)


def _retry_after(headers) -> int | None:
    """Seconds from a Retry-After header (a number or an HTTP date)."""
    value = (headers.get("Retry-After") if headers is not None else None) or ""
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    try:
        when = email.utils.parsedate_to_datetime(value).timestamp()
        return max(0, int(when - time.time()))
    except (TypeError, ValueError, OverflowError):
        return None


# API keys look like this; an error text that repeats one is masked before
# it reaches the screen
_KEY_LIKE = re.compile(r"\b(sk-[A-Za-z0-9_\-*]{6,}|gsk_[A-Za-z0-9]{6,}|AIza[0-9A-Za-z_\-]{10,}|"
                       r"xai-[A-Za-z0-9]{6,}|pplx-[A-Za-z0-9]{6,}|sk-ant-[A-Za-z0-9_\-]{6,})")


def redact(text: str, key: str = "") -> str:
    if key and len(key) >= 6:
        text = text.replace(key, "***")
    return _KEY_LIKE.sub("***", text)


def get_json(url: str, headers: dict, *, timeout: float, max_bytes: int,
             token: CancelToken | None = None, retries: int = 1):
    """GET a JSON document with a time limit and a size limit.

    GET is idempotent, so one retry is allowed, and only for a transient
    failure (connection reset, 502/503/504); never after a timeout (that would
    double the wait) nor after a cancellation. Raises OSError/ValueError.
    """
    req = urllib.request.Request(url, headers=headers, method="GET")
    for attempt in range(retries + 1):
        if token is not None and token.canceled:
            raise Canceled()
        # the time limit covers the whole download, not just each read
        own = token.child() if token is not None else CancelToken()
        timer = threading.Timer(timeout, own.cancel, args=("deadline",))
        timer.daemon = True
        timer.start()
        try:
            with open_url(req, read_timeout=timeout, token=own) as resp:
                body = resp.read(max_bytes + 1)
            if own.canceled:
                raise (Canceled() if own.reason == "canceled" else TimeoutError("deadline"))
            if len(body) > max_bytes:
                raise ValueError("reply too large")
            return json.loads(body.decode("utf-8"))
        except OSError as e:
            if own.canceled and not isinstance(e, urllib.error.HTTPError):
                raise (Canceled() if own.reason == "canceled" else TimeoutError("deadline")) from None
            if not isinstance(e, (urllib.error.URLError, ConnectionResetError,
                                  ConnectionAbortedError)):
                raise
            if isinstance(e, urllib.error.HTTPError):
                if e.code in (502, 503, 504) and attempt < retries:
                    continue
                raise
            reason = getattr(e, "reason", e)
            if isinstance(reason, (ConnectionResetError, ConnectionAbortedError)) and attempt < retries:
                continue
            raise
        except http.client.RemoteDisconnected:
            if attempt < retries and not own.canceled:
                continue
            raise OSError("remote disconnected") from None
        finally:
            timer.cancel()
            own.close()
    raise OSError("unreachable")


@dataclass
class Message:
    role: str            # "user" | "assistant"
    content: str


@dataclass
class ToolSpec:
    """Description of a tool (action) the AI can request."""
    name: str
    description: str
    schema: dict         # JSON schema of the parameters


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    """A provider's reply to one conversation turn."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"    # end_turn | tool_use | refusal | max_tokens
    error: str = ""                  # ProviderError.kind when the text is an error message


@dataclass
class ProviderConfig:
    name: str                        # internal id (claude, gemini, ...)
    label: str                       # name shown to the user
    kind: str                        # "cloud" | "local"
    model: str = ""
    endpoint: str = ""
    api_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    system: str = ""
    timeout: float = 0.0             # seconds, whole reply; 0 = default (TOTAL_TIMEOUT)
    stream: bool = True              # reply appears while it is being written
    context: int = 0                 # context window (local models only); 0 = model default


class Provider:
    """Base of every provider. `chat` runs one turn; `stream` runs one streamed."""

    # Can the provider use ZETA's actions (tool calling)? Those that do not
    # can answer straight away in streaming mode: the reply appears while it
    # is being written, instead of all at once at the end.
    uses_tools = True

    def __init__(self, config: ProviderConfig):
        self.config = config
        # Maximum wait time, when it needs to be shorter than usual: the
        # connection test cannot freeze a window for two minutes if the
        # network does not respond.
        self.timeout: float | None = None
        # The conversation turn in progress: Stop (or a newer question)
        # cancels it, closing the connection of the request being made.
        self.cancel_token: CancelToken | None = None

    # --- Public API ---
    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> Reply:
        raise NotImplementedError

    def stream(self, messages: list[Message],
               on_text: Callable[[str], None]) -> Reply:
        """Text-only streaming. Providers without streaming fall back to chat."""
        reply = self.chat(messages)
        if reply.text:
            on_text(reply.text)
        return reply

    def offered_models(self) -> list[str]:
        """The models the service actually offers (for automatic fallback).
        Every provider able to tell overrides this; [] = unknown."""
        return []

    def available(self) -> bool:
        """True if the provider is configured and usable."""
        if self.config.kind == "cloud":
            return bool(self.config.api_key)
        return True

    def test(self, timeout: float = 25.0) -> tuple[bool, str]:
        """Actually test the connection and report the outcome, in the user's language.

        Checking for a key is not enough: an expired key, a model that no
        longer exists or a network with no outbound access all look the same
        ("configured") until you try. Here the smallest possible request is
        made and the real outcome is reported.
        """
        if self.config.kind == "cloud" and not self.config.api_key:
            return False, tr("The API key is missing.")
        prev_tokens, prev_timeout = self.config.max_tokens, self.timeout
        self.config.max_tokens, self.timeout = 16, timeout
        try:
            self.chat([Message(role="user", content="ok")])
            return True, tr("Connected (model {model}).").format(
                model=self.config.model or tr("default"))
        except ProviderError as e:
            return False, str(e)
        except NotImplementedError:
            return False, tr("This provider can't be used yet.")
        except Exception as e:  # noqa: BLE001 - the test must never bring down the UI
            return False, tr("Unexpected error: {error}").format(error=e)
        finally:
            self.config.max_tokens, self.timeout = prev_tokens, prev_timeout

    # --- Common helpers ---
    def cancel(self) -> None:
        """Abort the request in progress (called from another thread)."""
        token = self.cancel_token
        if token is not None:
            token.cancel()

    def _limits(self, streaming: bool) -> tuple[float, float]:
        """(read timeout, total time cap) for one request.

        The read timeout is how long to wait for the first piece of the reply
        (and, while streaming, between two pieces); the cap is the whole
        reply. «Maximum Wait Time» in Settings › AI (config.timeout) sets the
        cap; the connection test sets everything shorter (self.timeout).
        """
        kind = "local" if self.config.kind == "local" else "cloud"
        read = (FIRST_TOKEN_TIMEOUT if streaming else WHOLE_REPLY_TIMEOUT)[kind]
        total = self.config.timeout if self.config.timeout and self.config.timeout > 0 else TOTAL_TIMEOUT[kind]
        if self.timeout:
            read, total = min(read, self.timeout), min(total, self.timeout)
        return min(read, total), total

    def _unreachable(self, reason) -> "ProviderError":
        """Network failure reasons in the user's language (previously the raw
        "timed out", "Name or service not known"... came through)."""
        # Check the error type and code first: the system text may be
        # translated (in GTK apps libc speaks the user's language).
        m = str(reason).lower()
        num = getattr(reason, "errno", None)
        if isinstance(reason, TimeoutError) or "timed out" in m or "timeout" in m:
            explanation = tr("it didn't respond in time")
        elif (isinstance(reason, socket.gaierror) or "name or service" in m
              or "temporary failure in name resolution" in m or "nodename" in m):
            explanation = tr("no internet connection, or DNS isn't responding")
        elif isinstance(reason, ConnectionRefusedError) or num == errno.ECONNREFUSED or "refused" in m:
            explanation = tr("connection refused")
        elif num in (errno.ENETUNREACH, errno.EHOSTUNREACH) or "unreachable" in m:
            explanation = tr("network unreachable")
        else:
            explanation = redact(str(reason), self.config.api_key)
        return ProviderError(tr("Can't reach {name}: {reason}.").format(
            name=self.config.label, reason=explanation), retryable=True, kind="network")

    def _interrupted(self, token: CancelToken, error, started: bool, read: float,
                     total: float) -> "ProviderError":
        """Why a request ended without a reply: canceled, too slow, network."""
        if token.canceled:
            if token.reason == "deadline":
                return ProviderError(tr("{name} took longer than {seconds} seconds and the request "
                                        "was stopped. Try a shorter question, or raise the "
                                        "maximum wait time in Settings › AI.").format(
                    name=self.config.label, seconds=int(total)), kind="timeout")
            return Canceled()
        if isinstance(error, (TimeoutError, socket.timeout)):
            if started:
                msg = tr("{name} stopped sending the reply (nothing for {seconds} seconds).")
            elif self.config.kind == "local":
                msg = tr("The local model didn't start replying within {seconds} seconds. "
                         "The computer may be busy or short of memory: try again, or "
                         "choose a smaller model in Settings › AI.")
            else:
                msg = tr("{name} didn't start replying within {seconds} seconds. "
                         "Try again in a moment.")
            return ProviderError(msg.format(name=self.config.label, seconds=int(read)),
                                 retryable=True, kind="timeout")
        return self._unreachable(error)

    def _open(self, url: str, payload: dict, headers: dict, streaming: bool):
        """Send the request: (response, token, deadline timer, limits)."""
        read, total = self._limits(streaming)
        parent = self.cancel_token
        token = parent.child() if parent is not None else CancelToken()
        timer = threading.Timer(total, token.cancel, args=("deadline",))
        timer.daemon = True
        timer.start()
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            if token.canceled:
                raise Canceled()
            resp = open_url(req, read_timeout=read, token=token)
        except urllib.error.HTTPError as e:
            timer.cancel()
            token.close()
            raise self._http_error(e.code, self._read_error_body(e), e.headers) from None
        except urllib.error.URLError as e:
            timer.cancel()
            token.close()
            raise self._interrupted(token, e.reason, False, read, total) from None
        except (TimeoutError, OSError, http.client.HTTPException) as e:
            timer.cancel()
            token.close()
            raise self._interrupted(token, e, False, read, total) from None
        except Canceled:
            timer.cancel()
            token.close()
            raise
        return resp, token, timer, (read, total)

    @staticmethod
    def _read_error_body(e) -> str:
        try:
            return e.read(64 * 1024).decode("utf-8", "replace")
        except (OSError, http.client.HTTPException):
            return ""

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        resp, token, timer, (read, total) = self._open(url, payload, headers, streaming=False)
        try:
            body = resp.read(MAX_REPLY_BYTES + 1)
            if len(body) > MAX_REPLY_BYTES:
                raise ProviderError(tr("{name}: the reply is too large.").format(
                    name=self.config.label), kind="error")
            if token.canceled:
                raise self._interrupted(token, None, True, read, total)
            return json.loads(body.decode("utf-8"))
        except ValueError:
            if token.canceled:
                raise self._interrupted(token, None, True, read, total) from None
            raise ProviderError(tr("{name}: the reply can't be read.").format(
                name=self.config.label), kind="error") from None
        except (TimeoutError, OSError, http.client.HTTPException) as e:
            raise self._interrupted(token, e, False, read, total) from None
        finally:
            timer.cancel()
            resp.close()
            token.close()

    def _post_stream(self, url: str, payload: dict, headers: dict) -> Iterator[bytes]:
        resp, token, timer, (read, total) = self._open(url, payload, headers, streaming=True)
        started = False
        try:
            for raw in resp:
                if token.canceled:
                    break
                started = True
                yield raw
            if token.canceled:
                raise self._interrupted(token, None, started, read, total)
        except (TimeoutError, OSError, http.client.HTTPException, ValueError) as e:
            raise self._interrupted(token, e, started, read, total) from None
        finally:
            timer.cancel()
            resp.close()
            token.close()

    def _http_error(self, code: int, body: str, headers=None) -> ProviderError:
        """An HTTP error status as a clear message plus a stable kind."""
        detail = ""
        try:
            j = json.loads(body)
            err = j.get("error") if isinstance(j, dict) else None
            if isinstance(err, dict):
                detail = str(err.get("message", "") or err.get("type", ""))
            elif isinstance(err, list) and err and isinstance(err[0], dict):   # Gemini, sometimes
                detail = str((err[0].get("error") or {}).get("message", ""))
            elif err:
                detail = str(err)
            elif isinstance(j, dict):
                detail = str(j.get("message", "") or j.get("detail", ""))
        except (ValueError, AttributeError):
            detail = body[:200]
        detail = redact(detail.strip(), self.config.api_key)[:300]
        low = detail.lower()
        name, model = self.config.label, self.config.model or tr("default")
        retry_after = _retry_after(headers)
        if code == 401 or (code == 400 and ("api key" in low or "api_key" in low)):
            # Gemini replies 400 "API key not valid" instead of 401
            return ProviderError(tr("{name}: invalid or missing API key. Check it in Settings › AI.")
                                 .format(name=name), status=code, kind="auth")
        if code == 402 or "insufficient balance" in low or "insufficient_quota" in low or "credit" in low:
            return ProviderError(tr("{name}: the account has no credit left (the API is paid "
                                    "separately from the web chat). Top it up on the service's "
                                    "site.").format(name=name), status=code, kind="quota")
        if code == 403:
            return ProviderError(tr("{name}: access denied for this API key.").format(name=name),
                                 status=code, kind="auth")
        if code == 429:
            if retry_after:
                msg = tr("{name}: too many requests (rate limit). Try again in {seconds} seconds.").format(
                    name=name, seconds=retry_after)
            else:
                msg = tr("{name}: too many requests (rate limit) or the free quota is used up. "
                         "Try again later.").format(name=name)
            return ProviderError(msg, retryable=True, status=code, kind="rate_limit",
                                 retry_after=retry_after)
        if code == 404 or (code in (400, 422) and "model" in low and
                           any(w in low for w in ("not found", "not exist", "does not exist",
                                                  "unknown", "invalid model", "not supported"))):
            # "model" / "not found" are what assistant.py looks for to
            # recognize a model that no longer exists
            return ProviderError(tr("{name}: model or endpoint not found ({model}).").format(
                name=name, model=model), status=code, kind="model")
        if code == 413 or "context length" in low or "too long" in low or "maximum context" in low:
            return ProviderError(tr("{name}: the request is too long for this model. Clear the "
                                    "conversation (zeta --forget) or ask a shorter question.").format(
                name=name), status=code, kind="too_long")
        if code >= 500:
            return ProviderError(tr("{name}: service error or overloaded, try again later.").format(
                name=name), retryable=True, status=code, kind="server")
        return ProviderError("%s: %s" % (name, detail or tr("error {code}").format(code=code)),
                             status=code, kind="bad_request")

    def _error_message(self, code: int, body: str) -> str:
        """Kept for callers that only need the text."""
        return str(self._http_error(code, body))

    def _stream_failed(self, detail) -> ProviderError:
        """An error the service reports in the middle of a streamed reply."""
        if isinstance(detail, dict):
            text = str(detail.get("message", "") or detail.get("type", ""))
            code = detail.get("code")
        else:
            text, code = str(detail or ""), None
        low = text.lower()
        if "overloaded" in low or code in (500, 502, 503, 529):
            return self._http_error(503, json.dumps({"error": {"message": text}}))
        if "rate" in low and "limit" in low:
            return self._http_error(429, json.dumps({"error": {"message": text}}))
        if "not found" in low and "model" in low:
            return self._http_error(404, json.dumps({"error": {"message": text}}))
        return ProviderError("%s: %s" % (self.config.label,
                                         redact(text, self.config.api_key)[:300] or tr("error")),
                             kind="error")


# Preferred models when the default one no longer exists (names change over
# time): fast ones first. They are matched as substrings of the name.
FAVORITES = {
    "claude": ["claude-haiku-5", "claude-sonnet-5", "haiku", "sonnet"],
    "gemini": ["gemini-3.8-flash", "gemini-3.5-flash", "flash", "gemini"],
    "openai": ["gpt-6-luna", "gpt-5.6-terra", "gpt-6", "gpt-5", "gpt-4.1-mini"],
    "deepseek": ["deepseek-flash", "deepseek-v4-flash", "deepseek-chat"],
    "qwen": ["qwen3.8-flash", "flash", "qwen-plus", "plus", "qwen-turbo", "qwen-max"],
    "perplexity": ["sonar"],
    "mistral": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest", "mistral"],
    "groq": ["gpt-oss-20b", "gpt-oss", "llama", "qwen"],
    "xai": ["grok-4", "grok"],
    "openrouter": ["openrouter/auto"],
}
_NON_CHAT = ("embed", "image", "tts", "audio", "whisper", "moderation", "guard", "realtime",
             "transcribe", "vision-preview", "search-preview", "dall-e", "veo", "imagen", "live")


def choose_model(provider_id: str, offered: list[str]) -> str:
    """The chat model to use among those offered, according to FAVORITES."""
    chat = [m for m in offered if m and not any(x in m.lower() for x in _NON_CHAT)]
    for part in FAVORITES.get(provider_id, []):
        found = sorted((m for m in chat if part in m.lower()), reverse=True)
        # on a tie, prefer the undated name (an alias that tracks updates)
        found.sort(key=lambda m: (not m.lower().startswith(part), len(m)))
        if found:
            return found[0]
    return chat[0] if chat else ""
