# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — saves to the Desktop whatever is dragged from the browser.

An image or a file dragged from Firefox arrives as a web address, not as a
file: the Desktop used to ignore them. Here:
  - a file or an image is actually downloaded; the download goes to a hidden
    «.name.partial» file that gets its real name only once it is complete,
    so an interrupted download never leaves a broken file that looks fine;
  - a link to a page becomes a shortcut (a small .html that opens the page
    in the browser), not a copy of the page;
  - embedded images ("data:") are decoded;
  - two files with the same name never overwrite each other: «name (2).png».
Every error comes back as a readable message, never as an exception.
"""
from __future__ import annotations

import base64
import html
import mimetypes
import os
import re
import shutil
import socket
import urllib.error
import urllib.parse
import urllib.request

from i18n import tr
from system.release import product_token

MAX_SIZE = 4 * 1024 ** 3            # 4 GB: beyond that we give up (and say why)
CHUNK = 256 * 1024
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) " + product_token()


def safe_name(name: str, default: str = "download") -> str:
    """A valid file name: no folders, no hidden or empty names."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().lstrip(".")
    name = re.sub(r"\s+", " ", name)
    if len(name) > 180:
        base, ext = os.path.splitext(name)
        name = base[:180 - len(ext)] + ext
    return name or default


def unique_name(folder: str, name: str) -> str:
    dest = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    n = 2
    while os.path.lexists(dest):
        dest = os.path.join(folder, "%s (%d)%s" % (base, n, ext))
        n += 1
    return dest


def _extension(kind: str) -> str:
    kind = (kind or "").split(";")[0].strip().lower()
    known_types = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
            "image/svg+xml": ".svg", "application/pdf": ".pdf", "text/plain": ".txt",
            "application/zip": ".zip", "audio/mpeg": ".mp3", "video/mp4": ".mp4"}
    return known_types.get(kind) or mimetypes.guess_extension(kind) or ""


def _name_from_response(url: str, headers) -> str:
    cd = headers.get("Content-Disposition", "") if headers else ""
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", cd)
    if m:
        return urllib.parse.unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd)
    if m:
        return m.group(1).strip()
    return urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path))


def _write(folder: str, name: str, source, length: int | None) -> tuple:
    """Write in chunks to a partial file and rename it only once complete."""
    if length and length > MAX_SIZE:
        return False, tr("The file is too large ({size} MB).").format(size=length // 1024 ** 2), None
    if length:
        free_space = shutil.disk_usage(folder).free
        if length > free_space - 200 * 1024 ** 2:
            return False, tr("Not enough disk space for “{name}”.").format(name=name), None
    partial = os.path.join(folder, ".%s.partial" % name)
    written = 0
    try:
        with open(partial, "wb") as f:
            while True:
                chunk = source.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_SIZE:
                    raise ValueError("too large")
                f.write(chunk)
        if length and written < length:
            raise ConnectionError("interrupted at %d of %d bytes" % (written, length))
        if written == 0:
            raise ValueError("empty")
        dest = unique_name(folder, name)
        os.replace(partial, dest)
        return True, tr("Saved to the Desktop: {name}").format(name=os.path.basename(dest)), dest
    except ConnectionError:
        _remove(partial)
        return False, tr("The download of “{name}” was interrupted. Try again.").format(name=name), None
    except ValueError as e:
        _remove(partial)
        return False, (tr("The website sent an empty file.") if str(e) == "empty"
                       else tr("The file is too large.")), None
    except (socket.timeout, TimeoutError):
        _remove(partial)
        return False, tr("The website stopped responding while downloading “{name}”.").format(name=name), None
    except OSError as e:
        _remove(partial)
        return False, tr("Could not write “{name}” to the Desktop: {error}").format(
            name=name, error=e.strerror or e), None


def _remove(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _from_data(url: str, folder: str) -> tuple:
    m = re.match(r"data:([^;,]*)((?:;[^;,]*)*),(.*)", url, re.S)
    if not m:
        return False, tr("The dragged content is not valid."), None
    kind, options, data = m.group(1) or "text/plain", m.group(2), m.group(3)
    try:
        raw_bytes = base64.b64decode(data, validate=False) if ";base64" in options \
            else urllib.parse.unquote_to_bytes(data)
    except (ValueError, TypeError):
        return False, tr("The dragged content is not valid."), None
    if not raw_bytes:
        return False, tr("The dragged content is empty."), None
    import io
    name = (tr("image") if kind.startswith("image/") else tr("file")) + _extension(kind)
    return _write(folder, name, io.BytesIO(raw_bytes), len(raw_bytes))


def _write_link_file(folder: str, url: str, title: str) -> tuple:
    # «News / Sport» is a title, not a path: the slash becomes a hyphen
    title = safe_name((title or urllib.parse.urlparse(url).netloc).replace("/", "-"), tr("Link"))
    dest = unique_name(folder, title + ".html")
    u = html.escape(url, quote=True)
    body = ('<!doctype html><meta charset="utf-8"><title>%s</title>'
             '<meta http-equiv="refresh" content="0; url=%s">'
             '<p><a href="%s">%s</a></p>\n' % (html.escape(title), u, u, u))
    try:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(body)
    except OSError as e:
        return False, tr("Could not create the link: {error}").format(error=e.strerror or e), None
    return True, tr("Link created on the Desktop: {name}").format(name=os.path.basename(dest)), dest


def from_url(url: str, folder: str, title: str | None = None, timeout: int = 30) -> tuple:
    """(ok, message, path). Never raises."""
    url = (url or "").strip()
    if url.startswith("data:"):
        return _from_data(url, folder)
    pieces = urllib.parse.urlparse(url)
    if pieces.scheme not in ("http", "https") or not pieces.netloc:
        return False, tr("“{url}” is not an address that can be downloaded.").format(url=url[:80]), None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            kind = r.headers.get("Content-Type", "")
            attachment = "attachment" in r.headers.get("Content-Disposition", "").lower()
            if kind.startswith("text/html") and not attachment:
                # a page: create a shortcut named after its title
                start = r.read(256 * 1024).decode("utf-8", "replace")
                m = re.search(r"<title[^>]*>(.*?)</title>", start, re.S | re.I)
                t = title or (html.unescape(m.group(1)).strip() if m else "")
                return _write_link_file(folder, url, t)
            name = safe_name(_name_from_response(r.geturl(), r.headers), "download")
            if not os.path.splitext(name)[1]:
                name += _extension(kind)
            try:
                length = int(r.headers.get("Content-Length") or 0) or None
            except ValueError:
                length = None
            return _write(folder, name, r, length)
    except urllib.error.HTTPError as e:
        return False, tr("The website returned an error ({code}): the file is not available.").format(code=e.code), None
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, socket.timeout):
            return False, tr("The website is not responding."), None
        if isinstance(reason, socket.gaierror):
            return False, tr("Website unreachable: unknown address, or the computer "
                             "is not connected to the internet."), None
        if isinstance(reason, ConnectionRefusedError):
            return False, tr("The website refused the connection."), None
        if isinstance(reason, __import__("ssl").SSLError):
            return False, tr("Insecure connection: the website’s certificate is not valid."), None
        return False, tr("Website unreachable: {reason}").format(reason=reason), None
    except (socket.timeout, TimeoutError):
        return False, tr("The website is not responding."), None
    except (OSError, ValueError) as e:
        return False, tr("Download failed: {error}").format(error=e), None


def data(folder: str, name: str, raw_bytes: bytes, kind: str = "") -> tuple:
    """Bytes already at hand (the image the browser handed over with the
    drag): saved as they are, through the same partial file."""
    import io
    if not raw_bytes:
        return False, tr("The dragged content is empty."), None
    name = safe_name(name, tr("image"))
    if not os.path.splitext(name)[1]:
        name += _extension(kind) or ".bin"
    return _write(folder, name, io.BytesIO(raw_bytes), len(raw_bytes))


def name_from_url(url: str, kind: str = "") -> str:
    """The file name an address implies («.../photo.jpg?x=1» -> photo.jpg)."""
    base = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path))
    base = safe_name(base, tr("image"))
    if kind and not os.path.splitext(base)[1]:
        base += _extension(kind)
    return base


def text(folder: str, content: str) -> tuple:
    """Dragged text (not an address): it becomes a text file."""
    if not content.strip():
        return False, tr("The dragged text is empty."), None
    dest = unique_name(folder, tr("Dragged text") + ".txt")
    try:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content if content.endswith("\n") else content + "\n")
    except OSError as e:
        return False, tr("Could not save the text: {error}").format(error=e.strerror or e), None
    return True, tr("Text saved to the Desktop: {name}").format(name=os.path.basename(dest)), dest
