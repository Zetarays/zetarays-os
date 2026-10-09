# ZETA RAYS Intelligence

The AI layer of ZETA RAYS OS: ZETA, the assistant. One interface for several
providers, a closed catalog of system actions that are checked after they run,
and an optional local conversation memory. It is written in standard-library
Python: **no dependencies to install** (network calls use `urllib`).

Code: `/usr/lib/zeta/intelligence/` (providers, registry, memory, voice) and
`/usr/lib/zeta/intelligence/agente/` (understanding, actions, verification).

## Providers

| Provider | Type | Endpoint and default model |
|---|---|---|
| Ollama | local | `http://127.0.0.1:11434`; uses the installed model (`llama3.2:1b` ships with the image) |
| Claude (Anthropic) | online | `api.anthropic.com`, `claude-haiku-5-5` |
| Gemini (Google) | online | `generativelanguage.googleapis.com`, `gemini-3.8-flash` |
| OpenAI | online | `api.openai.com`, `gpt-6-luna` |
| DeepSeek | online | `api.deepseek.com`, `deepseek-flash` |
| Qwen | online | DashScope, OpenAI-compatible mode, `qwen3.8-flash` |
| Perplexity | online | `api.perplexity.ai`, `sonar` |
| Mistral | online | `api.mistral.ai`, `mistral-small-latest` |
| Groq | online | `api.groq.com`, `openai/gpt-oss-20b` |
| xAI Grok | online | `api.x.ai`, `grok-4.7` |
| OpenRouter | online | `openrouter.ai`, `openrouter/auto` |
| Custom | any | any OpenAI-compatible service, online or on this computer (LM Studio, vLLM, llama.cpp): address and model are set by the user |

Each online service starts with a fast model; another one can be chosen in
**Settings > AI**. If the configured model no longer exists, ZETA asks the
service for its model list, picks a fast one and remembers it.

### Automatic provider choice

1. the provider chosen by the user, if it is ready;
2. **Ollama**, if it is running with a local model (offline first);
3. the first online provider with a key configured.

ZETA RAYS therefore works **without internet**: the local model is included in
the image.

## API keys

Keys are **never** in the code or in configuration files. They are entered in
**Settings > AI** and stored:

1. in the system keyring (Secret Service, unlocked at login), when one is
   running;
2. otherwise as systemd user credentials (`systemd-creds --user`): one
   encrypted file per key in `~/.config/zeta/chiavi/` (folder 0700, files
   0600), readable only by the same user on the same computer.

A plain-text `chiavi.json` from earlier versions is converted and then deleted;
it is used only if `systemd-creds` is missing. Keys are sent only to the
provider they belong to, and never appear in logs or URLs.

The rest of the configuration (default provider, models, endpoints, advanced
options) is in `~/.config/zeta/intelligence.json`.

## Actions: closed catalog, verification, consent

The AI never runs arbitrary shell commands. A request goes through one chain:

1. **local understanding** (`agente/capire.py`): English and Italian phrases
   are recognized in milliseconds, without the network or the model;
   compound requests ("create a folder and then open it") become several
   actions in order;
2. if that is not enough, **the model chooses one action** from the catalog
   (a JSON answer constrained to the action names; the arguments must appear
   in the request). Online services that support tool calling get the same
   catalog as tools;
3. actions that need consent **ask first**, showing what will be touched;
4. every action **checks the real state** of the system afterwards: the
   answer is the result of that check, never a courtesy "done".

The catalog (`agente/capacita.py`) has 58 actions on apps, windows, files and
folders, settings, volume, brightness, Wi-Fi, Bluetooth, the Dock, processes,
software and the location of installed programs. Each has a risk level:

| Level | Meaning | Consent |
|---|---|---|
| read | only looks (status, lists, where a program is) | no |
| normal | changes something that is easy to undo (open, move, volume, theme) | no |
| confirm | delete, force close, install or remove software, log out, restart, shut down, close all windows | **yes** |

File operations are confined to the home folder and external drives
(`/media`, `/run/media`, `/mnt`). A few older informational actions (system
info, disk, IP address, battery) still go through the earlier engine in
`actions.py`, which uses numeric permission levels 0 to 4 and asks for
consent at levels 3 and 4.

Every action is written to `~/.local/share/zeta/actions.log`, with passwords,
keys and tokens hidden.

## Finding programs

`system/programmi.py` answers "where is X?", "which command starts X?" and
"which package provides X?" from the real system: the app registry (APT,
Flatpak, AppImage, `/opt`, `/usr/local`, the user's own entries), every
directory of `$PATH` plus the sbin directories, the owning Debian package and
its version, and systemd services. ZETA uses it for questions such as "where
is blender?" or "find my appimages", and `zeta-app find NAME` prints the same
answer in the terminal. When an app is installed more than once (APT and
Flatpak, for example), ZETA lists the installations and asks which one to use
("open blender flatpak").

## Languages and voice

ZETA understands commands in English and Italian, whatever the system
language. The model replies in the language of the request; the results of
actions are written in the language of the ZETA RAYS apps (English or
Italian). Speech recognition is
offline (Vosk, English and Italian models) and follows the system language by
default; replies can be read aloud with espeak-ng. Nothing leaves the
computer.

## Memory

Local, in `~/.local/share/zeta/history.jsonl`; passwords typed in a request
are replaced with `***` before saving. Only the last 20 exchanges are used as
context, and executed commands are kept out of it. `zeta --forget` clears the
memory; `{"enabled": false}` in `~/.config/zeta/memory.json` stops saving it.
Nothing goes to an online service except as part of a request to the provider
the user chose.

## Command line

```bash
zeta                      interactive conversation
zeta "how much disk space do I have?"
zeta --provider claude    force a provider for this session
zeta --status             provider status
zeta --forget             clear the conversation memory
zeta -- <question>        a question that starts like one of the commands below
zeta system | memory | processes | repositories | diagnose
zeta ai status | ai test [service] | shell status
```

The Italian forms (`--stato`, `--oblio`, `sistema`, `memoria`, `processi`,
`diagnosi`) still work. `zeta-core` opens the graphical interface, with the
particle sphere.

## Security and ethics

The system prompt tells the model to help willingly and to refuse only
requests that are clearly illegal or harm other people; security work on the
user's own or authorized systems is legitimate. ZETA has no action that
attacks other systems, never acts on its own initiative, and asks for consent
before anything destructive.
