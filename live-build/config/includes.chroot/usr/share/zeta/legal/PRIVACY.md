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

**Where**: `deb.debian.org`, `security.debian.org` and their mirrors.
**When**: when you check for updates or install apps (Settings › Software
Update, Synaptic, or `apt`). On an installed system, also once a day for the
automatic security updates (on by default after installation), and once a
week if you turn on the update reminder. Never in the live session unless
you ask.
**What**: which packages you request. Your IP address is visible to the
server, as with any download.
**ZETA RAYS updates** come from `zetarays.org/apt` in the same way, at the
same moments: before each package check the system asks that address
whether the ZETA RAYS repository is there (one small request, nothing about
you or the computer is sent), and uses it only if it answers.
**Can it be avoided**: yes. Turn off "Install security updates
automatically" in Settings › Software Update, and do not update. This is not
recommended: updates bring security fixes.

## 2. The ZETA assistant

**ZETA uses only AI models that run on your computer.** Since ZETA RAYS 2.5
there are no online AI services in the system: no remote model of any
company, no API keys, and no fallback to the
cloud when the local model is busy or short of memory (ZETA then uses a
smaller local model, or tells you). Questions, answers, the conversation,
the things you ask ZETA to remember, your voice and your files never leave
the computer. It works offline.

The model runs in Ollama, which listens only on `127.0.0.1` (this computer)
and has its own cloud features switched off (`OLLAMA_NO_CLOUD=1`): Ollama's
"cloud" models, which would run on ollama.com, cannot be used, and ZETA
refuses them.

**Downloading another model (only if you ask).** *Settings › AI › Download a
model* fetches the model files from `registry.ollama.ai` (the Ollama
library). Only the name of the model is sent, as with any download. The
models included in the image need no download.

**Looking up current information (on by default).** A model only knows
the world up to its training date. For questions about current facts (who
holds an office, news, prices, versions, weather, results) ZETA looks up
public sources first, so that the answer is current. Only those questions
do: everything else stays on the computer. You can turn it off with the
switch in *Settings › AI › Current Information*.

| What | Where it goes |
|---|---|
| Your question, shortened to its key words | `it.wikipedia.org` or `en.wikipedia.org` (search and page extract) |
| The same, only if you also turn it on | `api.duckduckgo.com` (instant answers) |
| A question about Linux or a command, shortened to its key words | `wiki.archlinux.org` (the ArchWiki; the command's manual page is read on the computer) |

Only the question is sent: never the conversation, never your files, never
anything else. No cookies are kept, the requests identify themselves as
ZETA RAYS (User-Agent), and they stop after 5 seconds. The sources used are
shown under the answer with their address and date. With the switch off, or
without a network, ZETA says that current facts can't be verified.

What ZETA remembers is kept in one file, `~/.local/share/zeta/memory.db`,
readable by you only (permissions 600, folder 700): the latest conversation
(kept for 30 days unless you choose otherwise), the long-term memories you
asked for, and the web sources of earlier answers. *Settings › AI › Memory*
lists them, exports them and deletes them; `zeta --forget-all` deletes them
from the terminal. Nothing is remembered for the long term unless you ask.

Older versions could store API keys for online services in
`~/.config/zeta/keys/`. ZETA RAYS 2.5 no longer reads them; you can delete
that folder.

## 3. Speech recognition

It happens **on your computer**, with the Vosk engine and the speech models
included in the image. Microphone audio never leaves the computer and is
not recorded to disk: it is transcribed and discarded.

## 4. File search and text recognition

The document index and text recognition in images (OCR) work **locally
only**, with Tesseract. The index is kept in `~/.cache/zeta/` and never
leaves the computer. The same goes for "what's on my screen?" and "Ask ZETA
to Summarize": the picture of the window is read on the computer and deleted
at once, and the text goes only to the local model.

**Clipboard history** (Super+V) keeps the last 100 things you copied in
`~/.cache/cliphist`, readable by you only. What password managers mark as a
password is never saved. The switch in the history panel turns it off and
deletes it; "Clear all" deletes it at any time.

**Screenshots and screen recordings** are saved only where you see them
(Pictures/Screenshots, Videos/Screen recordings).

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

## 7. Security monitoring (ZETA WATCH)

ZETA WATCH works **on the computer only**. It reads the system's own logs
(logins, administrator actions, new users, firewall, open ports) and writes
what it finds to `/var/log/zeta-watch/`, readable only by administrators.
No event, no address and no log is sent anywhere. Blocking an address
after repeated wrong SSH passwords happens in the local firewall.

Two security tools download only their own data, never anything about you:

- **ClamAV** (antivirus) updates its virus signatures from
  `database.clamav.net`, at most once a day and at low priority, on an
  installed system only.
- **Suricata** (network monitoring) is not installed by default. If you
  turn it on in *Settings › ZETA WATCH*, it is installed from Debian and
  downloads the Emerging Threats Open rules from `rules.emergingthreats.net`.

The rootkit checks (rkhunter, chkrootkit) work offline.

## Where your data lives on the computer

| What | Where |
|---|---|
| Desktop settings | `~/.config/zeta/` |
| Conversations and memories of ZETA | `~/.local/share/zeta/memory.db` |
| What ZETA did on the computer (passwords hidden) | `~/.local/share/zeta/actions.log` |
| Search index, cache | `~/.cache/zeta/` |
| Clipboard history | `~/.cache/cliphist/` |
| Screenshots and recordings | `~/Pictures/Screenshots/`, `~/Videos/Screen recordings/` |
| Login records | `/var/lib/wtmpdb/` |
| ZETA WATCH events | `/var/log/zeta-watch/` (administrators only) |

They are your files, on your disk. Deleting them deletes the data.

## Live system

When you start from a USB stick or an image without installing, **nothing is
written to the computer's disk**: everything stays in memory and disappears
when you shut down.

---

*Last updated: with ZETA RAYS OS 3.5.*
