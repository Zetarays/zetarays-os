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

MASSIMO = 4 * 1024 ** 3            # 4 GB: oltre si rinuncia (e si dice perche')
PEZZO = 256 * 1024
AGENTE = "Mozilla/5.0 (X11; Linux x86_64) ZETA-RAYS/1.7"


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
        return False, "Il file è troppo grande (%d MB)." % (lunghezza // 1024 ** 2), None
    if lunghezza:
        libero = shutil.disk_usage(cartella).free
        if lunghezza > libero - 200 * 1024 ** 2:
            return False, "Non c'è abbastanza spazio sul disco per «%s»." % nome, None
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
            raise ConnectionError("interrotto a %d di %d byte" % (scritti, lunghezza))
        if scritti == 0:
            raise ValueError("vuoto")
        dest = nome_libero(cartella, nome)
        os.replace(parziale, dest)
        return True, "Salvato sulla Scrivania: %s" % os.path.basename(dest), dest
    except ConnectionError:
        _togli(parziale)
        return False, "Il download di «%s» si è interrotto: riprova." % nome, None
    except ValueError as e:
        _togli(parziale)
        return False, ("Il sito ha mandato un file vuoto." if str(e) == "vuoto"
                       else "Il file è troppo grande."), None
    except (socket.timeout, TimeoutError):
        _togli(parziale)
        return False, "Il sito ha smesso di rispondere durante il download di «%s»." % nome, None
    except OSError as e:
        _togli(parziale)
        return False, "Non riesco a scrivere «%s» sulla Scrivania: %s" % (nome, e.strerror or e), None


def _togli(percorso):
    try:
        os.unlink(percorso)
    except OSError:
        pass


def _da_data(url: str, cartella: str) -> tuple:
    m = re.match(r"data:([^;,]*)((?:;[^;,]*)*),(.*)", url, re.S)
    if not m:
        return False, "Il contenuto trascinato non è valido.", None
    tipo, opzioni, dati = m.group(1) or "text/plain", m.group(2), m.group(3)
    try:
        grezzi = base64.b64decode(dati, validate=False) if ";base64" in opzioni \
            else urllib.parse.unquote_to_bytes(dati)
    except (ValueError, TypeError):
        return False, "Il contenuto trascinato non è valido.", None
    if not grezzi:
        return False, "Il contenuto trascinato è vuoto.", None
    import io
    nome = ("immagine" if tipo.startswith("image/") else "file") + _estensione(tipo)
    return _scrivi(cartella, nome, io.BytesIO(grezzi), len(grezzi))


def _collegamento(cartella: str, url: str, titolo: str) -> tuple:
    # «Notizie / Sport» e' un titolo, non un percorso: la barra diventa un trattino
    titolo = nome_sicuro((titolo or urllib.parse.urlparse(url).netloc).replace("/", "-"), "Collegamento")
    dest = nome_libero(cartella, titolo + ".html")
    u = html.escape(url, quote=True)
    corpo = ('<!doctype html><meta charset="utf-8"><title>%s</title>'
             '<meta http-equiv="refresh" content="0; url=%s">'
             '<p><a href="%s">%s</a></p>\n' % (html.escape(titolo), u, u, u))
    try:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(corpo)
    except OSError as e:
        return False, "Non riesco a creare il collegamento: %s" % (e.strerror or e), None
    return True, "Collegamento creato sulla Scrivania: %s" % os.path.basename(dest), dest


def da_url(url: str, cartella: str, titolo: str | None = None, timeout: int = 30) -> tuple:
    """(ok, messaggio, percorso). Non solleva eccezioni."""
    url = (url or "").strip()
    if url.startswith("data:"):
        return _da_data(url, cartella)
    parti = urllib.parse.urlparse(url)
    if parti.scheme not in ("http", "https") or not parti.netloc:
        return False, "«%s» non è un indirizzo che si può scaricare." % url[:80], None
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
        return False, "Il sito ha risposto con un errore (%d): il file non è disponibile." % e.code, None
    except urllib.error.URLError as e:
        motivo = getattr(e, "reason", e)
        if isinstance(motivo, socket.timeout):
            return False, "Il sito non risponde.", None
        if isinstance(motivo, socket.gaierror):
            return False, ("Sito non raggiungibile: indirizzo sconosciuto, oppure il computer "
                           "non è collegato a Internet."), None
        if isinstance(motivo, ConnectionRefusedError):
            return False, "Il sito ha rifiutato la connessione.", None
        if isinstance(motivo, __import__("ssl").SSLError):
            return False, "Connessione non sicura: il certificato del sito non è valido.", None
        return False, "Sito non raggiungibile: %s" % motivo, None
    except (socket.timeout, TimeoutError):
        return False, "Il sito non risponde.", None
    except (OSError, ValueError) as e:
        return False, "Download non riuscito: %s" % e, None


def dati(cartella: str, nome: str, grezzi: bytes, tipo: str = "") -> tuple:
    """Byte gia' in mano (l'immagine che il browser ha consegnato con il
    trascinamento): si salvano cosi' come sono, con lo stesso file parziale."""
    import io
    if not grezzi:
        return False, "Il contenuto trascinato è vuoto.", None
    nome = nome_sicuro(nome, "immagine")
    if not os.path.splitext(nome)[1]:
        nome += _estensione(tipo) or ".bin"
    return _scrivi(cartella, nome, io.BytesIO(grezzi), len(grezzi))


def nome_da_url(url: str, tipo: str = "") -> str:
    """Il nome del file che un indirizzo lascia intendere («.../foto.jpg?x=1» -> foto.jpg)."""
    base = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path))
    base = nome_sicuro(base, "immagine")
    if tipo and not os.path.splitext(base)[1]:
        base += _estensione(tipo)
    return base


def testo(cartella: str, contenuto: str) -> tuple:
    """Testo trascinato (non un indirizzo): diventa un file di testo."""
    if not contenuto.strip():
        return False, "Il testo trascinato è vuoto.", None
    dest = nome_libero(cartella, "Testo trascinato.txt")
    try:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(contenuto if contenuto.endswith("\n") else contenuto + "\n")
    except OSError as e:
        return False, "Non riesco a salvare il testo: %s" % (e.strerror or e), None
    return True, "Testo salvato sulla Scrivania: %s" % os.path.basename(dest), dest
