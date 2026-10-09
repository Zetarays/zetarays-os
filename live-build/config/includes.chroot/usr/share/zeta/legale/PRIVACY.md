# ZETA RAYS OS — what leaves your computer

This document states plainly which data leaves your computer when you use
ZETA RAYS OS, where it goes and how to stop it.

*(Versione italiana: `PRIVACY.it.md`, in this same folder.)*

## The rule

**ZETA RAYS collects nothing.** There is no telemetry and no ZETA RAYS server
that the system sends statistics, error reports or usage habits to. The
system has no account and never asks you to sign up.

Anything that leaves the computer does so only to do something you asked
for, and the complete list is below.

## 1. System updates

**Where**: `deb.debian.org` and its mirrors.
**When**: when you update or install apps (Packages, or `apt`).
**What**: which packages you request. Your IP address is visible to the
server, as with any download.
**Can it be avoided**: yes, by not updating — but that is not recommended:
updates bring security fixes.

## 2. The ZETA assistant

ZETA works in two ways, and the difference matters.

**Local model (default).** The Llama 3.2 model runs **on your computer**.
Questions, answers and history never leave it. It also works offline.

**Cloud providers (only if you set one up).** If you enter an API key in
*Settings › AI*, your questions are sent to the provider you chose:

| Provider | Where the data goes |
|---|---|
| Claude (Anthropic) | `api.anthropic.com` |
| Gemini (Google) | `generativelanguage.googleapis.com` |
| OpenAI | `api.openai.com` |
| DeepSeek | `api.deepseek.com` |
| Qwen (Alibaba) | `dashscope-intl.aliyuncs.com` |
| Perplexity | `api.perplexity.ai` |
| Mistral | `api.mistral.ai` |
| Groq | `api.groq.com` |
| xAI Grok | `api.x.ai` |
| OpenRouter | `openrouter.ai` (which in turn forwards to the chosen model) |
| Custom | the address you enter (if it is `localhost`, it stays on the computer) |

From then on, **that provider's** terms and privacy policy apply, not these.
ZETA RAYS neither sees nor keeps any of that traffic.
**Without an API key, none of these connections take place.**

API keys are stored in the system keyring, if one is running; otherwise in
a file only you can read, `~/.config/zeta/chiavi.json` (permissions 600,
folder 700), as ssh and the command-line tools of cloud services do. They
never appear in logs, in diagnostic reports or in process arguments.

## 3. Speech recognition

It happens **on your computer**, with the Vosk engine and the speech models
included in the image. Microphone audio never leaves the computer and is
not recorded to disk: it is transcribed and discarded.

## 4. File search and text recognition

The document index and text recognition in images (OCR) work **locally
only**, with Tesseract. The index is kept in `~/.cache/zeta/` and never
leaves the computer.

## 5. System Monitor — network location

This is the only outgoing request that might surprise you, so it is worth
reading.

The Monitor's *Map* page shows where the computer appears to be connected
from. To do so it queries **`ipwho.is`**, an external service, which derives
city, country and provider from your public IP address.

- **What is sent**: your public IP address (implicitly, as with any
  connection) or an address you explicitly ask about.
- **What is not sent**: no data about the computer, no user name, no
  content.
- **When**: only when you open the Monitor with that feature turned on.
- **Caching**: the result is kept in `~/.cache/zeta/geo.json` so the request
  is not repeated.
- **How to stop it**: geolocation can be turned off in the Monitor itself.
  With it off, no request is made.

A `ping` to a host you type, also in the Monitor, obviously contacts that
host: that is the point of the command.

## 6. Web browser

Firefox ESR has its own privacy policy and its own connections to Mozilla
(updates, tracking protection). ZETA RAYS does not change or intercept them:
Mozilla's privacy policy applies.

## Where your data lives on the computer

| What | Where |
|---|---|
| Desktop settings | `~/.config/zeta/` |
| Conversations with ZETA | `~/.local/share/zeta/` |
| Search index, cache | `~/.cache/zeta/` |
| Cloud provider API keys | system keyring |
| Login records | `/var/lib/wtmpdb/` |

They are your files, on your disk. Deleting them deletes the data.

## Live system

When you start from a USB stick or an image without installing, **nothing is
written to the computer's disk**: everything stays in memory and disappears
when you shut down.

---

*Last updated: with ZETA RAYS OS 2.0.*
