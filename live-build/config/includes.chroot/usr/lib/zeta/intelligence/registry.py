# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — gestore dei provider.

Legge la configurazione da ~/.config/zeta/intelligence.json. Le chiavi API non
stanno in quel file: hanno un posto loro, e mai vengono scritte nel codice o
inviate a servizi diversi da quello del provider scelto.

Dove finiscono le chiavi
------------------------
Prima si prova il portachiavi del sistema (Secret Service, tramite
`secret-tool`). ZETA RAYS però è minimale e NON installa un demone che
implementi quel servizio: su un sistema appena installato `secret-tool store`
fallisce con «org.freedesktop.secrets was not provided by any .service files»,
e la chiave veniva buttata via in silenzio mentre le Impostazioni scrivevano
«Chiave salvata». Per questo c'è la seconda strada, che è quella usata di
solito: le credenziali cifrate di systemd (`systemd-creds --user`). Ogni chiave
è un file cifrato in ~/.config/zeta/chiavi/ (cartella 0700, file 0600) con la
chiave segreta della macchina, custodita da systemd e leggibile solo da root
(e dal chip TPM, se c'è): la decifra solo lo stesso utente, solo su questo
computer. Copiato altrove, o letto da un altro utente, il file è inutile.
Nessun demone in più, nessuna password da digitare.
Il vecchio file in chiaro (chiavi.json) viene convertito e poi cancellato.
Solo se systemd-creds mancasse si ripiega su quel file, solo dell'utente.

Ordine di scelta del provider predefinito:
  1. il provider indicato dall'utente
  2. Ollama, se è in esecuzione con un modello locale (offline-first)
  3. il primo provider cloud con una chiave configurata
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .providers.base import Provider, ProviderConfig
from .providers.claude import ClaudeProvider
from .providers.gemini import GeminiProvider
from .providers.ollama import OllamaProvider
from .providers.openai_compat import OpenAICompatProvider

CONFIG_DIR = Path(os.path.expanduser("~/.config/zeta"))
CONFIG_FILE = CONFIG_DIR / "intelligence.json"

# provider disponibili: id -> (classe, etichetta, tipo)
CATALOG = {
    "claude":   (ClaudeProvider,       "Claude",   "cloud"),
    "gemini":   (GeminiProvider,       "Gemini",   "cloud"),
    "openai":   (OpenAICompatProvider, "OpenAI",   "cloud"),
    "deepseek": (OpenAICompatProvider, "DeepSeek", "cloud"),
    "qwen":     (OpenAICompatProvider, "Qwen",     "cloud"),
    "perplexity": (OpenAICompatProvider, "Perplexity", "cloud"),
    "mistral":  (OpenAICompatProvider, "Mistral",  "cloud"),
    "groq":     (OpenAICompatProvider, "Groq",     "cloud"),
    "xai":      (OpenAICompatProvider, "xAI Grok", "cloud"),
    "openrouter": (OpenAICompatProvider, "OpenRouter", "cloud"),
    # Qualsiasi servizio compatibile OpenAI, in rete o sul computer (LM Studio,
    # vLLM, llama.cpp): indirizzo e modello li scrive l'utente.
    "personalizzato": (OpenAICompatProvider, "Personalizzato (compatibile OpenAI)", "cloud"),
    "ollama":   (OllamaProvider,       "Ollama",   "local"),
}

# Istruzioni brevi e in positivo: il modello locale (1B) con un elenco di
# divieti rifiutava anche richieste innocue («scrivi una frase su Roma»:
# visto). Provate su 8 richieste normali: 0 rifiuti, contro 1-2 di prima.
DEFAULT_SYSTEM = (
    "Sei ZETA, l'intelligenza di ZETA RAYS OS. Rispondi sempre in italiano, in modo breve, "
    "chiaro e gentile. Aiuta volentieri: scrivi testi e poesie, spiega, rispondi alle domande, "
    "dai consigli. Rifiuta soltanto le richieste chiaramente illegali o che danneggiano altre "
    "persone; il lavoro di sicurezza su sistemi propri o autorizzati e' legittimo. Non dire mai "
    "di aver fatto un'azione sul computer: le azioni le esegue il sistema, che ne comunica "
    "l'esito vero. Il sistema operativo si chiama ZETA RAYS OS."
)


KEYS_FILE = CONFIG_DIR / "chiavi.json"          # vecchio formato, in chiaro
CREDS_DIR = CONFIG_DIR / "chiavi"               # chiavi cifrate (systemd-creds)
_decifrate: dict = {}                            # nella memoria di questo processo


def _creds_ok() -> bool:
    """systemd-creds --user funziona qui? (una prova per processo)"""
    cached = getattr(_creds_ok, "_cache", None)
    if cached is not None:
        return cached
    ok = False
    try:
        p = subprocess.run(["systemd-creds", "encrypt", "--user", "--name=zeta-sonda", "-", "-"],
                           input=b"sonda", capture_output=True, timeout=10)
        ok = p.returncode == 0 and len(p.stdout) > 20
    except (FileNotFoundError, subprocess.SubprocessError):
        ok = False
    _creds_ok._cache = ok
    return ok


def _cred_file(name: str) -> Path:
    sicuro = "".join(c for c in name if c.isalnum() or c in "-_") or "chiave"
    return CREDS_DIR / (sicuro + ".cred")


def _cred_get(name: str) -> str:
    if name in _decifrate:
        return _decifrate[name]
    f = _cred_file(name)
    if not f.exists():
        return ""
    try:
        p = subprocess.run(["systemd-creds", "decrypt", "--user", "--name=zeta-" + name, str(f), "-"],
                           capture_output=True, timeout=10)
        v = p.stdout.decode("utf-8", "replace").strip() if p.returncode == 0 else ""
    except (FileNotFoundError, subprocess.SubprocessError):
        v = ""
    _decifrate[name] = v
    return v


def _cred_set(name: str, value: str) -> bool:
    _decifrate.pop(name, None)
    f = _cred_file(name)
    if not value:
        try:
            f.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True
    try:
        CREDS_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(CONFIG_DIR, 0o700)
        os.chmod(CREDS_DIR, 0o700)
        p = subprocess.run(["systemd-creds", "encrypt", "--user", "--name=zeta-" + name, "-", "-"],
                           input=value.encode(), capture_output=True, timeout=10)
        if p.returncode != 0 or not p.stdout:
            return False
        tmp = f.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(p.stdout)
        os.replace(tmp, f)
    except (OSError, subprocess.SubprocessError):
        return False
    # si controlla che si rilegga davvero, prima di dire «salvata»
    return _cred_get(name) == value


def _migra_file_in_chiaro() -> None:
    """chiavi.json (in chiaro, versioni precedenti) -> file cifrati, poi via."""
    if getattr(_migra_file_in_chiaro, "_fatto", False):
        return
    _migra_file_in_chiaro._fatto = True
    if not KEYS_FILE.exists() or not _creds_ok():
        return
    vecchie = _file_keys()
    for nome, valore in vecchie.items():
        valore = str(valore).strip()
        if valore and not _cred_set(nome, valore):
            return                      # qualcosa non va: il file resta, niente si perde
    try:
        dim = KEYS_FILE.stat().st_size
        with open(KEYS_FILE, "r+b") as fh:          # si sovrascrive prima di cancellare
            fh.write(b"\0" * dim)
            fh.flush()
            os.fsync(fh.fileno())
        KEYS_FILE.unlink()
    except OSError:
        pass


def _secret_service() -> bool:
    """Vero solo se sul sistema c'è davvero un portachiavi che risponde.

    Non basta che `secret-tool` sia installato: è solo il programma che chiede.
    Serve un demone che offra org.freedesktop.secrets. La risposta si tiene in
    memoria: la domanda si fa una volta per processo, non a ogni chiave.
    """
    cached = getattr(_secret_service, "_cache", None)
    if cached is not None:
        return cached
    ok = False
    try:
        out = subprocess.run(["secret-tool", "search", "--unlock", "zeta-provider", "_sonda"],
                             capture_output=True, text=True, timeout=5)
        # 0 = trovato, 1 = non trovato ma il servizio c'è; l'assenza del
        # servizio si riconosce dal messaggio, non dal codice di uscita.
        ok = "not provided by any .service" not in (out.stderr or "")
    except (FileNotFoundError, subprocess.SubprocessError):
        ok = False
    _secret_service._cache = ok
    return ok


def _file_keys() -> dict:
    try:
        with open(KEYS_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _file_keys_write(d: dict) -> bool:
    """Scrive il file delle chiavi leggibile solo dall'utente.

    I permessi si mettono PRIMA di scrivere il contenuto: creare il file e poi
    restringerlo lascia una finestra, per quanto breve, in cui la chiave è
    leggibile da chiunque sul computer.
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(CONFIG_DIR, 0o700)
        tmp = KEYS_FILE.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, KEYS_FILE)
        os.chmod(KEYS_FILE, 0o600)
        return True
    except OSError:
        return False


def _keyring_get(name: str) -> str:
    """La chiave API di un provider. Stringa vuota se non c'è."""
    if _secret_service():
        try:
            out = subprocess.run(["secret-tool", "lookup", "zeta-provider", name],
                                 capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
    _migra_file_in_chiaro()
    if _creds_ok():
        return _cred_get(name)
    return str(_file_keys().get(name, "")).strip()


def keyring_set(name: str, value: str) -> bool:
    """Salva (o cancella, con valore vuoto) la chiave di un provider.

    Restituisce True SOLO se la chiave è davvero finita da qualche parte: chi
    chiama deve dirlo all'utente. Prima questo valore veniva ignorato e le
    Impostazioni scrivevano «Chiave salvata» anche quando non era vero.
    """
    value = (value or "").strip()
    if _secret_service():
        try:
            if value:
                p = subprocess.run(["secret-tool", "store", "--label=ZETA RAYS %s" % name,
                                    "zeta-provider", name], input=value, text=True, timeout=5)
            else:
                p = subprocess.run(["secret-tool", "clear", "zeta-provider", name],
                                   capture_output=True, timeout=5)
            if p.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
    _migra_file_in_chiaro()
    if _creds_ok():
        return _cred_set(name, value)
    d = _file_keys()
    if value:
        d[name] = value
    else:
        d.pop(name, None)
    return _file_keys_write(d)


def keyring_where() -> str:
    """Dove vengono tenute le chiavi, da mostrare nelle Impostazioni."""
    if _secret_service():
        return "portachiavi del sistema"
    if _creds_ok():
        return "cifrate in %s (solo tu, solo su questo computer)" % CREDS_DIR
    return str(KEYS_FILE)


def load_settings() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    tmp.replace(CONFIG_FILE)


class Registry:
    def __init__(self):
        self.settings = load_settings()
        self.system = self.settings.get("system", DEFAULT_SYSTEM)

    def _config(self, provider_id: str) -> ProviderConfig:
        cls, label, kind = CATALOG[provider_id]
        opts = self.settings.get("providers", {}).get(provider_id, {})
        return ProviderConfig(
            name=provider_id, label=label, kind=kind,
            model=opts.get("model", ""),
            endpoint=opts.get("endpoint", ""),
            api_key="" if kind == "local" else _keyring_get(provider_id),
            temperature=float(opts.get("temperature", 0.7)),
            # il modello locale risponde breve di proposito (veloce anche su
            # computer lenti): senza una scelta dell'utente resta cosi'
            max_tokens=int(opts.get("max_tokens",
                                    OllamaProvider.MAX_TOKEN if kind == "local" else 4096)),
            timeout=float(opts.get("timeout", 0) or 0),
            stream=bool(opts.get("stream", True)),
            context=int(opts.get("context", 0) or 0),
            system=self.system,
        )

    def get(self, provider_id: str) -> Provider:
        cls = CATALOG[provider_id][0]
        return cls(self._config(provider_id))

    def scegli(self, provider_id: str) -> None:
        """Imposta quale AI usare. «auto» torna alla scelta automatica."""
        s = dict(self.settings)
        if provider_id in (None, "", "auto"):
            s.pop("default", None)
        elif provider_id in CATALOG:
            s["default"] = provider_id
        else:
            raise ValueError("provider sconosciuto: %s" % provider_id)
        save_settings(s)
        self.settings = s

    def set_option(self, provider_id: str, key: str, value) -> None:
        """Salva un'opzione di un provider (modello, endpoint...)."""
        s = dict(self.settings)
        prov = dict(s.get("providers", {}))
        conf = dict(prov.get(provider_id, {}))
        if value in (None, ""):
            conf.pop(key, None)
        else:
            conf[key] = value
        prov[provider_id] = conf
        s["providers"] = prov
        save_settings(s)
        self.settings = s

    def test(self, provider_id: str) -> tuple[bool, str]:
        """Prova il collegamento di un provider e restituisce (riuscito, messaggio)."""
        if provider_id not in CATALOG:
            return False, "Provider sconosciuto."
        try:
            return self.get(provider_id).test()
        except Exception as e:  # noqa: BLE001 - una prova non deve mai far cadere l'app
            return False, "Errore inatteso: %s" % e

    def resolve_default(self) -> Provider:
        """Sceglie il provider da usare (vedi ordine in cima al file)."""
        chosen = self.settings.get("default")
        if chosen and chosen in CATALOG:
            prov = self.get(chosen)
            if prov.available():
                return prov
        # offline-first: prova Ollama
        ollama = self.get("ollama")
        if ollama.available():
            return ollama
        # primo cloud con chiave
        for pid, (_cls, _label, kind) in CATALOG.items():
            if kind == "cloud":
                prov = self.get(pid)
                if prov.available():
                    return prov
        return ollama  # anche se non pronto: ZETA mostrerà come configurarlo

    def status(self) -> list[dict]:
        """Stato di ogni provider, per le Impostazioni e la diagnostica."""
        rows = []
        for pid, (_cls, label, kind) in CATALOG.items():
            prov = self.get(pid)
            row = {"id": pid, "label": label, "kind": kind,
                   "ready": prov.available(), "model": prov.config.model,
                   "endpoint": prov.config.endpoint,
                   "model_default": modello_predefinito(pid)}
            if pid == "ollama":
                row["local_models"] = prov.list_models()
            rows.append(row)
        return rows


def modello_predefinito(provider_id: str) -> str:
    """Il modello usato quando l'utente non ne sceglie uno."""
    from .providers import claude, gemini, openai_compat
    if provider_id == "claude":
        return claude.DEFAULT_MODEL
    if provider_id == "gemini":
        return gemini.DEFAULT_MODEL
    return openai_compat.PRESETS.get(provider_id, ("", "", ""))[2]
