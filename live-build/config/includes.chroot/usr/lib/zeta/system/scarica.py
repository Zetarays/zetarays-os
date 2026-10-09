# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — salva sulla Scrivania cio' che si trascina dal browser.

Un'immagine o un file trascinati da Firefox arrivano come indirizzo web, non
come file: prima la Scrivania li ignorava. Qui:
  - un file o un'immagine si scaricano davvero; il download va in un file
    nascosto «.nome.parziale» che prende il nome vero solo a download finito,
    cosi' un download interrotto non lascia un file rotto con l'aria di buono;
  - un link a una pagina diventa un collegamento (un piccolo .html che apre
    la pagina nel browser), non una copia della pagina;
  - le immagini incorporate («data:») si decodificano;
  - due file con lo stesso nome non si sovrascrivono: «nome (2).png».
Ogni errore torna come messaggio leggibile, mai come eccezione.
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

MASSIMO = 4 * 1024 ** 3            # 4 GB: oltre si rinuncia (e si dice perche')
PEZZO = 256 * 1024
AGENTE = "Mozilla/5.0 (X11; Linux x86_64) ZETA-RAYS/2.0"


def nome_sicuro(nome: str, predefinito: str = "download") -> str:
    """Un nome di file valido: niente cartelle, niente nomi nascosti o vuoti."""
    nome = (nome or "").replace("\\", "/").split("/")[-1]
    nome = re.sub(r"[\x00-\x1f\x7f]", "", nome).strip().lstrip(".")
    nome = re.sub(r"\s+", " ", nome)
    if len(nome) > 180:
        base, ext = os.path.splitext(nome)
        nome = base[:180 - len(ext)] + ext
    return nome or predefinito


def nome_libero(cartella: str, nome: str) -> str:
    dest = os.path.join(cartella, nome)
    base, ext = os.path.splitext(nome)
    n = 2
    while os.path.lexists(dest):
        dest = os.path.join(cartella, "%s (%d)%s" % (base, n, ext))
        n += 1
    return dest


def _estensione(tipo: str) -> str:
    tipo = (tipo or "").split(";")[0].strip().lower()
    noti = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
            "image/svg+xml": ".svg", "application/pdf": ".pdf", "text/plain": ".txt",
            "application/zip": ".zip", "audio/mpeg": ".mp3", "video/mp4": ".mp4"}
    return noti.get(tipo) or mimetypes.guess_extension(tipo) or ""


def _nome_da_risposta(url: str, intestazioni) -> str:
    cd = intestazioni.get("Content-Disposition", "") if intestazioni else ""
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", cd)
    if m:
        return urllib.parse.unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd)
    if m:
        return m.group(1).strip()
    return urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path))


def _scrivi(cartella: str, nome: str, sorgente, lunghezza: int | None) -> tuple:
    """Scrive a pezzi in un file parziale e lo rinomina solo se e' completo."""
    if lunghezza and lunghezza > MASSIMO:
        return False, tr("The file is too large ({size} MB).").format(size=lunghezza // 1024 ** 2), None
    if lunghezza:
        libero = shutil.disk_usage(cartella).free
        if lunghezza > libero - 200 * 1024 ** 2:
            return False, tr("Not enough disk space for “{name}”.").format(name=nome), None
    parziale = os.path.join(cartella, ".%s.parziale" % nome)
    scritti = 0
    try:
        with open(parziale, "wb") as f:
            while True:
                pezzo = sorgente.read(PEZZO)
                if not pezzo:
                    break
                scritti += len(pezzo)
                if scritti > MASSIMO:
                    raise ValueError("troppo grande")
                f.write(pezzo)
        if lunghezza and scritti < lunghezza:
            raise ConnectionError("interrupted at %d of %d bytes" % (scritti, lunghezza))
        if scritti == 0:
            raise ValueError("vuoto")
        dest = nome_libero(cartella, nome)
        os.replace(parziale, dest)
        return True, tr("Saved to the Desktop: {name}").format(name=os.path.basename(dest)), dest
    except ConnectionError:
        _togli(parziale)
        return False, tr("The download of “{name}” was interrupted. Try again.").format(name=nome), None
    except ValueError as e:
        _togli(parziale)
        return False, (tr("The website sent an empty file.") if str(e) == "vuoto"
                       else tr("The file is too large.")), None
    except (socket.timeout, TimeoutError):
        _togli(parziale)
        return False, tr("The website stopped responding while downloading “{name}”.").format(name=nome), None
    except OSError as e:
        _togli(parziale)
        return False, tr("Could not write “{name}” to the Desktop: {error}").format(
            name=nome, error=e.strerror or e), None


def _togli(percorso):
    try:
        os.unlink(percorso)
    except OSError:
        pass


def _da_data(url: str, cartella: str) -> tuple:
    m = re.match(r"data:([^;,]*)((?:;[^;,]*)*),(.*)", url, re.S)
    if not m:
        return False, tr("The dragged content is not valid."), None
    tipo, opzioni, dati = m.group(1) or "text/plain", m.group(2), m.group(3)
    try:
        grezzi = base64.b64decode(dati, validate=False) if ";base64" in opzioni \
            else urllib.parse.unquote_to_bytes(dati)
    except (ValueError, TypeError):
        return False, tr("The dragged content is not valid."), None
    if not grezzi:
        return False, tr("The dragged content is empty."), None
    import io
    nome = (tr("image") if tipo.startswith("image/") else tr("file")) + _estensione(tipo)
    return _scrivi(cartella, nome, io.BytesIO(grezzi), len(grezzi))


def _collegamento(cartella: str, url: str, titolo: str) -> tuple:
    # «Notizie / Sport» e' un titolo, non un percorso: la barra diventa un trattino
    titolo = nome_sicuro((titolo or urllib.parse.urlparse(url).netloc).replace("/", "-"), tr("Link"))
    dest = nome_libero(cartella, titolo + ".html")
    u = html.escape(url, quote=True)
    corpo = ('<!doctype html><meta charset="utf-8"><title>%s</title>'
             '<meta http-equiv="refresh" content="0; url=%s">'
             '<p><a href="%s">%s</a></p>\n' % (html.escape(titolo), u, u, u))
    try:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(corpo)
    except OSError as e:
        return False, tr("Could not create the link: {error}").format(error=e.strerror or e), None
    return True, tr("Link created on the Desktop: {name}").format(name=os.path.basename(dest)), dest


def da_url(url: str, cartella: str, titolo: str | None = None, timeout: int = 30) -> tuple:
    """(ok, messaggio, percorso). Non solleva eccezioni."""
    url = (url or "").strip()
    if url.startswith("data:"):
        return _da_data(url, cartella)
    parti = urllib.parse.urlparse(url)
    if parti.scheme not in ("http", "https") or not parti.netloc:
        return False, tr("“{url}” is not an address that can be downloaded.").format(url=url[:80]), None
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            tipo = r.headers.get("Content-Type", "")
            allegato = "attachment" in r.headers.get("Content-Disposition", "").lower()
            if tipo.startswith("text/html") and not allegato:
                # una pagina: si crea un collegamento con il suo titolo
                inizio = r.read(256 * 1024).decode("utf-8", "replace")
                m = re.search(r"<title[^>]*>(.*?)</title>", inizio, re.S | re.I)
                t = titolo or (html.unescape(m.group(1)).strip() if m else "")
                return _collegamento(cartella, url, t)
            nome = nome_sicuro(_nome_da_risposta(r.geturl(), r.headers), "download")
            if not os.path.splitext(nome)[1]:
                nome += _estensione(tipo)
            try:
                lunghezza = int(r.headers.get("Content-Length") or 0) or None
            except ValueError:
                lunghezza = None
            return _scrivi(cartella, nome, r, lunghezza)
    except urllib.error.HTTPError as e:
        return False, tr("The website returned an error ({code}): the file is not available.").format(code=e.code), None
    except urllib.error.URLError as e:
        motivo = getattr(e, "reason", e)
        if isinstance(motivo, socket.timeout):
            return False, tr("The website is not responding."), None
        if isinstance(motivo, socket.gaierror):
            return False, tr("Website unreachable: unknown address, or the computer "
                             "is not connected to the internet."), None
        if isinstance(motivo, ConnectionRefusedError):
            return False, tr("The website refused the connection."), None
        if isinstance(motivo, __import__("ssl").SSLError):
            return False, tr("Insecure connection: the website’s certificate is not valid."), None
        return False, tr("Website unreachable: {reason}").format(reason=motivo), None
    except (socket.timeout, TimeoutError):
        return False, tr("The website is not responding."), None
    except (OSError, ValueError) as e:
        return False, tr("Download failed: {error}").format(error=e), None


def dati(cartella: str, nome: str, grezzi: bytes, tipo: str = "") -> tuple:
    """Byte gia' in mano (l'immagine che il browser ha consegnato con il
    trascinamento): si salvano cosi' come sono, con lo stesso file parziale."""
    import io
    if not grezzi:
        return False, tr("The dragged content is empty."), None
    nome = nome_sicuro(nome, tr("image"))
    if not os.path.splitext(nome)[1]:
        nome += _estensione(tipo) or ".bin"
    return _scrivi(cartella, nome, io.BytesIO(grezzi), len(grezzi))


def nome_da_url(url: str, tipo: str = "") -> str:
    """Il nome del file che un indirizzo lascia intendere («.../foto.jpg?x=1» -> foto.jpg)."""
    base = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path))
    base = nome_sicuro(base, tr("image"))
    if tipo and not os.path.splitext(base)[1]:
        base += _estensione(tipo)
    return base


def testo(cartella: str, contenuto: str) -> tuple:
    """Testo trascinato (non un indirizzo): diventa un file di testo."""
    if not contenuto.strip():
        return False, tr("The dragged text is empty."), None
    dest = nome_libero(cartella, tr("Dragged text") + ".txt")
    try:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(contenuto if contenuto.endswith("\n") else contenuto + "\n")
    except OSError as e:
        return False, tr("Could not save the text: {error}").format(error=e.strerror or e), None
    return True, tr("Text saved to the Desktop: {name}").format(name=os.path.basename(dest)), dest
