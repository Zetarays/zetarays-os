# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — riconoscimento vocale offline.

Usa Vosk con un modello italiano. Tutto avviene in locale: nessun audio lascia
il computer. Se manca qualcosa, `status()` dice esattamente cosa, e ZETA
lo spiega invece di fingere che funzioni.

Punti a cui si è prestata attenzione:
  • il modello si carica UNA volta sola e resta in memoria (caricarlo a ogni
    frase costava secondi di attesa);
  • la lettura dal microfono non può mai bloccarsi: si usa una scadenza, così
    un microfono che non produce dati non pianta ZETA;
  • si smette di registrare appena la persona ha finito di parlare, invece di
    aspettare sempre lo stesso numero di secondi;
  • il processo di registrazione viene chiuso in ogni caso.

Attivazione:
  1. installare Vosk        (pip install vosk, oppure pacchetto di ZETA RAYS)
  2. scaricare un modello   in ~/.local/share/zeta/vosk/  o  /usr/share/vosk/
"""
from __future__ import annotations

import array
import json
import os
import select
import shutil
import subprocess
import threading
import time

# Un modello per lingua. Vosk ne carica uno solo e non riconosce da se' quale
# lingua stia sentendo: la scelta la fa il sistema (vedi lingua_scelta), non
# l'indovinello.
MODELLI = {
    "it": ["/usr/share/vosk/model-it"],
    "en": ["/usr/share/vosk/model-en"],
}
# Cartelle dove cercare comunque, per chi ne aggiunge uno a mano.
MODEL_DIRS = [
    os.path.expanduser("~/.local/share/zeta/vosk"),
    "/usr/share/vosk/model-it",
    "/usr/share/vosk/model-en",
    "/usr/share/vosk",
]
LINGUA_FILE = os.path.expanduser("~/.config/zeta/voce-lingua")

RATE = 16000
CHUNK = 3200                 # 0,1 s di audio a 16 kHz mono 16 bit
SOGLIA_VOCE = 450            # livello medio sopra il quale c'è voce
ATTESA_INIZIALE = 6.0        # secondi di pazienza prima che si parli
DURATA_MASSIMA = 15.0        # limite assoluto: non si registra all'infinito
SILENZIO_FINE = 1.1          # silenzio dopo la voce = frase finita

_modello = None
_lock = threading.Lock()


# --------------------------------------------------------------- disponibilità
def _valido(d: str) -> bool:
    return os.path.isdir(d) and os.path.isfile(os.path.join(d, "conf", "model.conf"))


def lingue_disponibili() -> list:
    """Le lingue per cui c'e' davvero un modello installato."""
    return [lang for lang, dirs in MODELLI.items() if any(_valido(d) for d in dirs)]


def lingua_scelta() -> str:
    """La lingua da ascoltare: quella scelta, altrimenti quella del sistema.

    Chi usa il sistema in inglese si aspetta che il microfono capisca
    l'inglese, senza doverlo dire. Chi vuole il contrario lo scrive una volta
    in ~/.config/zeta/voce-lingua.
    """
    try:
        with open(LINGUA_FILE) as f:
            scelta = f.read().strip().lower()[:2]
        if scelta in MODELLI and any(_valido(d) for d in MODELLI[scelta]):
            return scelta
    except OSError:
        pass
    sistema = (os.environ.get("LANG") or os.environ.get("LC_ALL") or "it")[:2].lower()
    if sistema in MODELLI and any(_valido(d) for d in MODELLI[sistema]):
        return sistema
    disponibili = lingue_disponibili()
    return disponibili[0] if disponibili else "it"


def _model_path() -> str | None:
    for d in MODELLI.get(lingua_scelta(), []):
        if _valido(d):
            return d
    for d in MODEL_DIRS:
        if _valido(d):
            return d
    return None


def _has_vosk() -> bool:
    try:
        import vosk  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _recorder() -> list | None:
    """Comando che scrive audio grezzo mono 16 kHz 16 bit su stdout."""
    if shutil.which("pw-record"):
        # --raw: senza, scriverebbe un'intestazione WAV che il riconoscitore
        # interpreterebbe come rumore.
        return ["pw-record", "--raw", "--rate=%d" % RATE, "--channels=1",
                "--format=s16", "-"]
    if shutil.which("parec"):
        return ["parec", "--format=s16le", "--rate=%d" % RATE, "--channels=1", "--raw"]
    if shutil.which("arecord"):
        return ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"]
    return None


def _microfono_presente() -> bool:
    """Vero se il sistema audio espone almeno una sorgente."""
    try:
        out = subprocess.run(["wpctl", "status"], capture_output=True, text=True,
                             timeout=4).stdout
    except (OSError, subprocess.SubprocessError):
        return True          # senza wpctl non possiamo dirlo: non blocchiamo
    dentro = False
    for riga in out.splitlines():
        if "Sources:" in riga:
            dentro = True
            continue
        if dentro:
            if "Filters" in riga or "Sinks" in riga:
                dentro = False
                continue
            if riga.strip(" │├─└\t") and any(c.isdigit() for c in riga):
                return True
    return False


def status() -> dict:
    """Perché il riconoscimento vocale è o non è disponibile."""
    mic = _recorder() is not None
    return {
        "vosk": _has_vosk(),
        "model": _model_path(),
        "mic": mic,
        "sorgente": mic and _microfono_presente(),
        "caricato": _modello is not None,
        "available": _has_vosk() and _model_path() is not None and mic,
    }


def available() -> bool:
    return status()["available"]


def why_unavailable() -> str:
    s = status()
    if not s["mic"]:
        return "Nessuno strumento di registrazione disponibile sul sistema."
    if not s["vosk"]:
        return ("Il motore vocale offline (Vosk) non è installato. "
                "Il comando scritto funziona già; per la voce installa Vosk e "
                "un modello italiano.")
    if not s["model"]:
        return ("Manca il modello vocale italiano. Copialo in "
                "~/.local/share/zeta/vosk/ per attivare i comandi a voce.")
    if not s["sorgente"]:
        return "Nessun microfono collegato."
    return "Riconoscimento vocale non disponibile."


# ------------------------------------------------------------------- modello
def preload() -> bool:
    """Carica il modello in memoria. Si può chiamare da un thread di sfondo."""
    global _modello
    if _modello is not None:
        return True
    if not available():
        return False
    with _lock:
        if _modello is not None:
            return True
        try:
            import vosk
            vosk.SetLogLevel(-1)          # niente rumore sul terminale
            _modello = vosk.Model(_model_path())
        except Exception:  # noqa: BLE001
            _modello = None
            return False
    return True


def _livello(dati: bytes) -> int:
    """Livello medio del pezzo di audio (0 = silenzio)."""
    if len(dati) < 2:
        return 0
    campioni = array.array("h")
    campioni.frombytes(dati[: len(dati) // 2 * 2])
    if not campioni:
        return 0
    return int(sum(abs(c) for c in campioni) / len(campioni))


def _confidenza(risultato: dict) -> float:
    """Quanto il motore è sicuro di ciò che ha capito (0 = per niente)."""
    parole = risultato.get("result") or []
    if not parole:
        return 0.0
    valori = [p.get("conf", 0.0) for p in parole]
    return sum(valori) / len(valori)


class ErroreMicrofono(Exception):
    pass


# ------------------------------------------------ seconda lettura dei comandi
# Il modello piccolo, a vocabolario libero, sbaglia spesso proprio le parole
# dei comandi («apri firefox» -> «app di firefox», «alza il volume» -> «al
# volume»: provato). Quando la prima trascrizione non e' un comando, lo stesso
# audio si rilegge con un vocabolario ridotto alle parole dei comandi e ai
# nomi delle app installate. Si usa solo se ne esce un comando valido.
_PAROLE_COMANDI = """
apri aprimi avvia lancia chiudi esci riavvia riapri passa vai torna mostrami mostra fammi vedere
crea nuova nuovo cerca trova dove elimina cancella sposta copia rinomina metti togli aggiungi
accendi spegni attiva disattiva alza abbassa aumenta diminuisci blocca sospendi riduci icona
ingrandisci schermo intero connetti collegati disconnetti installa disinstalla scarica
il lo la i gli le un una uno di del della dello dei delle nel nella nei sulla sul al alla allo a in
e poi dopo per con da dal dalla chiamata chiamato nome cartella file finestra
volume audio suono muto wifi rete internet bluetooth computer sistema
impostazioni terminale documenti download scaricati immagini foto musica video scrivania cestino
memoria ram cpu processore processi disco spazio batteria stato che ore sono giorno quanta quanto
sto usando lento rallenta dock sfondo tema chiaro scuro schermata screenshot più forte piano luminosità
sito pagina posta email browser editor testo calcolatrice
zero uno due tre quattro cinque sei sette otto nove dieci venti trenta quaranta cinquanta
sessanta settanta ottanta novanta cento percento
""".split()


def _vocabolario() -> list:
    parole = set(_PAROLE_COMANDI)
    try:
        from .agente import stato
        for a in stato.app_installate():
            if a.nascosta:
                continue
            for n in list(a.nomi) + [a.nome, a.binario]:
                for w in (n or "").lower().replace("-", " ").split():
                    if w.isalpha() and len(w) > 2:
                        parole.add(w)
    except Exception:  # noqa: BLE001 - senza nomi delle app si usano solo i comandi
        pass
    return sorted(parole) + ["[unk]"]


# Solo comandi con argomenti «chiusi» (un'app installata, una cartella nota,
# un numero): la seconda lettura sostituisce le parole che non conosce con
# quelle del vocabolario, e un nome di file come «viaggi» diventava «avvia»
# (provato). Creare, spostare, cercare o eliminare file: mai da qui.
_DA_VOCE = {"open_application", "close_application", "restart_application", "focus_application",
            "minimize_window", "maximize_window", "fullscreen_window", "open_folder", "open_settings",
            "set_volume", "set_brightness", "set_theme", "wifi_on", "wifi_off", "wifi_list",
            "network_status", "bluetooth_on", "bluetooth_off", "bluetooth_devices", "system_status",
            "list_processes", "list_running_applications", "current_time", "screenshot", "lock_screen"}


def _comando_valido(azioni) -> bool:
    """Ogni app nominata esiste davvero («chiudi video fox» no)."""
    from .agente import stato
    for _nome, args in azioni:
        app = args.get("app")
        if app and not stato.trova_app(app):
            return False
    return True


def _rileggi_comando(audio: bytes, rate: int, prima: str) -> tuple:
    """(testo, confidenza) se lo stesso audio, riletto con le sole parole dei
    comandi, da' un comando che ZETA capisce; altrimenti ("", 0)."""
    if not audio or _modello is None:
        return "", 0.0
    try:
        import vosk
        from .agente.capire import capire
        from .agente import capacita
        vosk.SetLogLevel(-2)        # le parole che il modello non ha: avvisi inutili
        k = vosk.KaldiRecognizer(_modello, rate, json.dumps(_vocabolario(), ensure_ascii=False))
        k.SetWords(True)
        k.AcceptWaveform(bytes(audio))
        r = json.loads(k.FinalResult())
    except Exception:  # noqa: BLE001
        return "", 0.0
    testo = (r.get("text") or "").strip()
    conf = _confidenza(r)
    if not testo or "[unk]" in testo or conf < 0.6:
        return "", 0.0
    azioni = capire(testo)
    if not azioni or any(n not in _DA_VOCE for n, _a in azioni) or not _comando_valido(azioni):
        return "", 0.0
    # Dev'esserci un legame con cio' che si e' sentito prima (una parola in
    # comune), a meno che il comando sia una semplice lettura («che ore sono»).
    comuni = {w for w in testo.split() if len(w) > 3} & {w for w in prima.lower().split() if len(w) > 3}
    solo_lettura = all(capacita.REGISTRO[n].rischio == "lettura" for n, _a in azioni if n in capacita.REGISTRO)
    if not comuni and not solo_lettura:
        return "", 0.0
    return testo, conf


def trascrivi(audio: bytes, rate: int = RATE) -> tuple:
    """(testo, confidenza) di un audio gia' registrato (16 bit mono)."""
    if not preload():
        return "", 0.0
    import vosk
    k = vosk.KaldiRecognizer(_modello, rate)
    k.SetWords(True)
    k.AcceptWaveform(bytes(audio))
    try:
        r = json.loads(k.FinalResult())
    except ValueError:
        return "", 0.0
    return _scegli(r, audio, rate)


def _scegli(risultato: dict, audio: bytes, rate: int) -> tuple:
    testo = (risultato.get("text") or "").strip()
    conf = _confidenza(risultato)
    try:
        from .agente.capire import capire
        azioni = capire(testo) if testo else None
        # un comando valido si tiene; «al volume» (senza «alza») e' quasi
        # sempre un verbo perso: si rilegge
        if azioni and _comando_valido(azioni) and not (
                len(azioni) == 1 and azioni[0][0] in ("set_volume", "set_brightness") and not azioni[0][1]):
            return testo, conf
    except Exception:  # noqa: BLE001
        return testo, conf
    alt, conf_alt = _rileggi_comando(audio, rate, testo)
    return (alt, conf_alt) if alt else (testo, conf)


class Recognizer:
    """Registra una frase e la trascrive. Non blocca mai a tempo indefinito."""

    def __init__(self, attesa: float = ATTESA_INIZIALE,
                 massimo: float = DURATA_MASSIMA,
                 silenzio: float = SILENZIO_FINE):
        self.attesa = attesa
        self.massimo = massimo
        self.silenzio = silenzio

    def listen(self, on_stato=None) -> str:
        """Restituisce il testo riconosciuto ("" se non si è capito nulla).

        on_stato, se passato, riceve "attesa" | "ascolto" | "elaborazione".
        """
        if not preload():
            raise ErroreMicrofono(why_unavailable())
        import vosk

        comando = _recorder()
        try:
            proc = subprocess.Popen(comando, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        except OSError as e:
            raise ErroreMicrofono("Non riesco ad aprire il microfono: %s" % e) from e

        kaldi = vosk.KaldiRecognizer(_modello, RATE)
        kaldi.SetWords(True)        # serve per sapere quanto è sicuro il risultato
        audio = bytearray()         # per la seconda lettura (vedi _rileggi_comando)
        inizio = time.monotonic()
        ultima_voce = None
        ha_parlato = False
        if on_stato:
            on_stato("attesa")
        try:
            while True:
                adesso = time.monotonic()
                if adesso - inizio > self.massimo:
                    break
                if not ha_parlato and adesso - inizio > self.attesa:
                    break                      # nessuno ha parlato
                if ha_parlato and ultima_voce and adesso - ultima_voce > self.silenzio:
                    break                      # frase finita
                # lettura con scadenza: un microfono muto non deve bloccarci
                pronto, _, _ = select.select([proc.stdout], [], [], 0.25)
                if not pronto:
                    continue
                dati = proc.stdout.read(CHUNK)
                if not dati:
                    break
                if _livello(dati) >= SOGLIA_VOCE:
                    if not ha_parlato and on_stato:
                        on_stato("ascolto")
                    ha_parlato = True
                    ultima_voce = time.monotonic()
                kaldi.AcceptWaveform(dati)
                audio.extend(dati)
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                try:
                    proc.kill()
                except OSError:
                    pass

        if not ha_parlato:
            return ""
        if on_stato:
            on_stato("elaborazione")
        try:
            risultato = json.loads(kaldi.FinalResult())
        except ValueError:
            return ""
        testo, self.ultima_confidenza = _scegli(risultato, audio, RATE)
        return testo

    ultima_confidenza = 0.0
