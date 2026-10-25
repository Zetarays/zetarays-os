# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — the interface of the local model, and the
HTTP plumbing it shares with the web lookup.

The model runs on this computer (Ollama on 127.0.0.1); the web lookup
(websearch.py) uses get_json() to fetch public sources. Every request has a
time limit and can be canceled from another thread.
No external dependencies: only urllib from the standard library.
"""
from __future__ import annotations

import errno
import functools
import http.client
import json
import socket
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterator

from i18n import tr


class ProviderError(Exception):
    """A provider error, carrying a message that is already user-readable.

    `kind` is a stable key (never shown, never translated) that the assistant
    and the tests use: model, too_long, server, bad_request, network,
    timeout, canceled, empty, memory, error.
    """

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None,
                 kind: str = "error"):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.kind = kind


class Canceled(ProviderError):
    """The user stopped the request (or a newer request replaced it)."""

    def __init__(self, message: str = ""):
        super().__init__(message or tr("Request canceled."), kind="canceled")


# --- time limits -----------------------------------------------------------
# Every request has three limits, so that nothing can leave ZETA waiting
# forever: reaching the server, the first piece of the reply, the whole reply.
# A local model on a modest computer may first have to be loaded into memory.
CONNECT_TIMEOUT = 10.0
FIRST_TOKEN_TIMEOUT = 60.0
# without streaming the server answers only when the whole reply is ready
WHOLE_REPLY_TIMEOUT = 120.0
TOTAL_TIMEOUT = 300.0
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
             token: CancelToken | None = None, local: bool = False):
    """urlopen with a connect timeout, a read timeout and cancellation.
    No cookie handler: nothing is stored between requests. `local`: a
    request to the model on this computer never goes through a proxy set in
    the environment (http_proxy would otherwise receive the conversation)."""
    handlers = [_TimedHTTPHandler(read_timeout, token), _TimedHTTPSHandler(read_timeout, token)]
    if local:
        handlers.insert(0, urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(req, timeout=CONNECT_TIMEOUT)


def local_urlopen(req, timeout: float):
    """urlopen for the model's server on this computer: no proxy, ever."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


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
class Reply:
    """A provider's reply to one conversation turn."""
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""                  # ProviderError.kind when the text is an error message


@dataclass
class ProviderConfig:
    name: str                        # internal id ("ollama")
    label: str                       # name shown to the user
    kind: str = "local"              # always "local" since 2.5
    model: str = ""
    endpoint: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    system: str = ""
    timeout: float = 0.0             # seconds, whole reply; 0 = default (TOTAL_TIMEOUT)
    stream: bool = True              # reply appears while it is being written
    context: int = 0                 # context window; 0 = model default


class Provider:
    """Base of the local model provider (and of the tests' stand-ins).
    `chat` runs one turn; `stream` runs one streamed."""

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
    def chat(self, messages: list[Message]) -> Reply:
        raise NotImplementedError

    def stream(self, messages: list[Message],
               on_text: Callable[[str], None]) -> Reply:
        """Text-only streaming. Providers without streaming fall back to chat."""
        reply = self.chat(messages)
        if reply.text:
            on_text(reply.text)
        return reply

    def available(self) -> bool:
        """True if the provider is usable."""
        return True

    def test(self, timeout: float = 25.0) -> tuple[bool, str]:
        """Actually test the connection and report the outcome, in the user's language.

        Here the smallest possible request is made and the real outcome is
        reported.
        """
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
        read = FIRST_TOKEN_TIMEOUT if streaming else WHOLE_REPLY_TIMEOUT
        total = self.config.timeout if self.config.timeout and self.config.timeout > 0 else TOTAL_TIMEOUT
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
            explanation = str(reason)
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
            else:
                msg = tr("The local model didn't start replying within {seconds} seconds. "
                         "The computer may be busy or short of memory: try again, or "
                         "choose a smaller model in Settings › AI.")
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
            resp = open_url(req, read_timeout=read, token=token, local=True)
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
        """An HTTP error status of the local server as a clear message plus a
        stable kind."""
        detail = ""
        try:
            j = json.loads(body)
            err = j.get("error") if isinstance(j, dict) else None
            if isinstance(err, dict):
                detail = str(err.get("message", "") or err.get("type", ""))
            elif err:
                detail = str(err)
            elif isinstance(j, dict):
                detail = str(j.get("message", "") or j.get("detail", ""))
        except (ValueError, AttributeError):
            detail = body[:200]
        detail = detail.strip()[:300]
        low = detail.lower()
        name, model = self.config.label, self.config.model or tr("default")
        if code == 404 or (code in (400, 422) and "model" in low and
                           any(w in low for w in ("not found", "not exist", "does not exist",
                                                  "unknown", "invalid model", "not supported"))):
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

    def _stream_failed(self, detail) -> ProviderError:
        """An error the server reports in the middle of a streamed reply."""
        if isinstance(detail, dict):
            text = str(detail.get("message", "") or detail.get("type", ""))
            code = detail.get("code")
        else:
            text, code = str(detail or ""), None
        low = text.lower()
        if "overloaded" in low or code in (500, 502, 503):
            return self._http_error(503, json.dumps({"error": {"message": text}}))
        if "not found" in low and "model" in low:
            return self._http_error(404, json.dumps({"error": {"message": text}}))
        return ProviderError("%s: %s" % (self.config.label, text[:300] or tr("error")), kind="error")
