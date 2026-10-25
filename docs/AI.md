# ZETA RAYS Intelligence

The AI layer of ZETA RAYS OS: ZETA, the assistant. Since 2.5 it is **local
only**: the models run on the computer (Ollama, which uses llama.cpp), there
is no online AI service, no API key and no fallback to the cloud. A closed
catalog of system actions is checked after each action runs; a local memory
keeps the conversation and what the user asks ZETA to remember; answers are
written and read aloud at the same time. Standard-library Python: **no
dependencies to install**.

Code: `/usr/lib/zeta/intelligence/` (models, memory, store, context, speech,
voice) and `/usr/lib/zeta/intelligence/agent/` (understanding, actions,
verification).

## Local only

| What | How it is enforced |
|---|---|
| One provider | `registry.CATALOG` holds only Ollama; the clients of online AI services were removed in 2.5 |
| Only this computer | `providers/ollama.py` accepts only loopback addresses (127.0.0.0/8, ::1, localhost); any other address in the settings or in `OLLAMA_HOST` is replaced with `127.0.0.1:11434` |
| No proxy | requests to the model bypass `http_proxy` (a proxy would otherwise receive the conversation) |
| Ollama's own cloud | `OLLAMA_NO_CLOUD=1` in `ollama.service` (the log says `Ollama cloud disabled: true`); `-cloud` models are refused by ZETA and by the download field |
| Listening | `OLLAMA_HOST=127.0.0.1:11434`; `zeta-diagnostics` prints who can reach port 11434 |
| Checked by | `zeta-selftest ai` (`ai_local_only`: providers, no cloud API hosts in the code, loopback rule, service settings) |

What still uses the network, only when the user wants it: the Wikipedia
lookup for current facts (only the question; Settings › AI), and downloading
another model from `registry.ollama.ai` (Settings › AI). Neither sends a
conversation, a memory or a file.

## Choosing the model

`models.py` looks at the computer once and picks a profile; the first
installed model of the profile's list is used, unless the user picked one in
Settings › AI.

| Profile | When | Models, best first | Context |
|---|---|---|---|
| `low-power` | Intel N-series processor (N100, N150, N200, N97, N95) | `granite4:micro-h`, `qwen3:4b-instruct` | 2048 |
| `8gb` | less than 12 GB of RAM | `granite4:micro-h`, `qwen3:4b-instruct` | 4096 |
| `16gb` | 12 GB or more | `qwen3:4b-instruct`, `granite4:micro-h` | 4096 |
| `large` | 24 GB or more and 8 or more processor threads | `granite4.1:8b` (recommended, download on click), `qwen3:4b-instruct`, `granite4:micro-h` | 8192 |

When the first model of the profile is not installed, Settings › AI shows it
as "Recommended for this computer" with a Download button: nothing is
downloaded without the user's click, and the download checks the free disk
space and whether the model fits the memory of the computer first.

When the usual model cannot be loaded because free memory is short, a
smaller installed model answers that question and the answer says so
(`models.fallback`); the next question goes back to the usual model. The
fallback is always local.

Thinking models (Qwen3.5, Gemma 4, Qwen3 hybrids) are asked not to think
(`"think": false`): a reasoning trace costs seconds before the first useful
word. Models that copy ZETA's note back into the answer have the copy
removed, on screen and in the voice (`context.strip_note_echo`).

### How the models were compared (October 2026)

Both `qwen3:4b-instruct` (Qwen3 4B Instruct 2507, Qwen team, Apache-2.0) and
`granite4:micro-h` (Granite 4.0 Micro, hybrid Mamba-2, IBM, Apache-2.0,
Italian officially supported) are in the image: about 4.4 GB together. Each
is the other's smaller or larger alternative.

Method: Ollama 0.40.10 in a Debian 13 container limited to 4 processor cores
and 16 GB (Apple silicon host, arm64), q8_0 KV cache, context 4096,
temperature 0.3, at most 220 tokens per answer; the same ZETA system prompt
and per-question note as the real assistant; 13 conversation prompts
(Italian and English: explanation, e-mail, poem, two arithmetic problems,
two coding questions, summary, conversation memory, a current fact with and
without a source) and the 10 command prompts of ZETA's action chooser
(JSON constrained to the action names). "Checks" are objective: the two
arithmetic answers, the remembered name, using the given source, not naming
an office holder from memory. Raw answers: `.cache/v25/bench/res-*.json`
in the build tree. Thinking models ran with thinking off, as ZETA runs them
(with thinking on, Qwen3.5 2B and Gemma 4 E2B returned only their reasoning
within 220 tokens).

| Model | Memory loaded | Writing (tokens/s) | Reading (tokens/s) | First word, median | Commands | Checks | Note leaks |
|---|---|---|---|---|---|---|---|
| lfm2.5:8b (think off) | 5.413GiB | 26.1 | 459 | 0.69 s | 6/10 | 4/5 | 13 |
| granite4:tiny-h | 4.507GiB | 22.3 | 414 | 0.81 s | 9/10 | 4/5 | 0 |
| gemma4:e2b-it-qat (think off) | 4.98GiB | 19.0 | 609 | 0.60 s | 10/10 | 4/5 | 3 |
| granite4:micro-h | 2.402GiB | 17.7 | 459 | 0.70 s | 9/10 | 5/5 | 0 |
| qwen3.5:2b (think off) | 3.57GiB | 15.5 | 150 | 2.18 s | 9/10 | 4/5 | 1 |
| ministral-3:3b | 3.606GiB | 12.9 | 447 | 0.72 s | 10/10 | 4/5 | 0 |
| qwen3.5:4b (think off) | 4.13GiB | 12.6 | 61 | 5.78 s | 10/10 | 4/5 | 0 |
| qwen3:4b-instruct | 3.222GiB | 12.5 | 351 | 0.97 s | 10/10 | 4/5 | 0 |
| granite4.1:3b | 2.583GiB | 12.4 | 406 | 0.82 s | 10/10 | 4/5 | 0 |
| gemma4:e4b-it-qat (think off) | 6.796GiB | 8.6 | 243 | 1.39 s | 9/10 | 4/5 | 1 |
| granite4.1:8b | 5.715GiB | 7.8 | 210 | 1.53 s | 10/10 | 4/5 | 0 |
| qwen3:8b (think off) | 5.576GiB | 7.8 | 197 | 1.80 s | 9/10 | 5/5 | 0 |

Not used, and why:
- **Liquid LFM2.5**: the 8B MoE writes fastest but always emits its
  reasoning (`<think>`, also with thinking off), chose 6/10 commands, the
  small models do not list Italian, and the LFM Open License limits
  commercial use by organizations above a revenue threshold, which a free
  distribution cannot pass on.
- **Qwen3.5 (2B, 4B)**: reading the prompt is 2-6 times slower in llama.cpp
  (hybrid attention), so the first word comes after 2-6 s; the 2B made
  spelling mistakes and copied ZETA's note into its answer.
- **Gemma 4 (E2B, E4B)**: very quick to start, but 5-7 GB in memory (the
  audio and image encoders are loaded too) and it copied the note into its
  answers.
- **Granite 4.0 Tiny (hybrid MoE)**: the fastest writer of the usable ones
  (22 tokens/s) but 4.5 GB in memory and one arithmetic mistake; a good
  choice to download on a 16 GB N100 for speed.
- **Ministral 3 3B, Granite 4.1 3B**: correct and quick, but less natural
  Italian (invented words, Portuguese spellings in code) than the two chosen.
- **Qwen3 8B**: correct, but 5.6 GB and 7.8 tokens/s; Granite 4.1 8B is
  equally fast with 10/10 commands and more fluent Italian, so it is the
  optional larger model.
- **DeepSeek R1 distills**: reasoning models that always think first.
- **Gemma 3 / 3n**: Gemma Terms of Use (use restrictions passed on to every
  user), not a free license.

**Intel N100: an estimate, not a measurement.** No N100 was available for
the tests. Writing speed on a CPU is limited mostly by memory bandwidth per
token: the N100 has one memory channel and four efficiency cores, so expect
roughly a third to a half of the speeds above (about 4-6 tokens/s for
Qwen3 4B, 6-9 for Granite 4.0 Micro), and 2-4 s to the first word of a
follow-up question. That is why the low-power profile prefers Granite 4.0
Micro and a 2048-token context. Measure on the real machine with
`zeta ai test` and `zeta-diagnostics` (section "local AI response").

## Memory

One SQLite file, `~/.local/share/zeta/memory.db` (permissions 600, folder
700), `store.py`:

| Table | What | Retention |
|---|---|---|
| `turns` | the conversation | 30 days by default (1, 7, 30, 90 or 365 in Settings › AI › Memory), at most 4000 messages |
| `facts` | long-term memories: only what the user asked ("remember that…", or added in Settings) | until deleted, at most 500 |
| `knowledge` | reference material with provenance: the verified facts shipped in `/usr/share/zeta/knowledge/reference.json` (date checked, source), web sources of earlier answers (address, retrieval date; reused for 30 days), documents the user gave with `zeta --learn FILE` | reference: replaced at every release; web: last 300 |

Search is SQLite full-text search with the **trigram** tokenizer: it matches
parts of words, so Italian and English inflections meet without a stemmer
per language, and multilingual keywords let an Italian question find an
English reference entry. A question with several meaningful words must
share at least two of them with a row ("president of France" does not bring
back the president of the United States). Measured: under a millisecond per
search.

Each question gets **at most three** matching long-term memories, in the
note that travels with the question, never the whole list. The history sent
to the model is a bounded window cut in blocks (see Speed). Exact duplicates
are refused and near-duplicates replace the older memory. A damaged file is
set aside (`memory.db.damaged-<time>`) and a new one is started. Deleting
uses SQL `DELETE` followed by `VACUUM`, so deleted text leaves the file.

Commands, in Italian and English (language data in
`i18n-data/memory.json`): "remember that…", "forget…", "what do you know
about me?". Settings › AI › Memory lists, deletes, exports (JSON in
Documents) and clears; `zeta --memories`, `--remember`, `--forget`,
`--forget-all`, `--learn` do the same in the terminal.

**No embedding model.** A multilingual embedding model (EmbeddingGemma 2,
Qwen3-Embedding 0.6B, bge-m3: 0.3-1.2 GB) was considered for semantic
search. It is not used: the Ollama service keeps one model in memory
(`OLLAMA_MAX_LOADED_MODELS=1`, so the chat model is never pushed out on an
8 GB computer), and every question would first load and run the embedding
model; with tens or hundreds of short memories the trigram search finds
them in under a millisecond. Encryption of the file is left to the disk
(the installer offers full-disk encryption): the file is private to the
user like the rest of the home folder.

## Current facts

A model does not know the world after its training date. Every question
carries today's date; for questions about facts that change (who holds an
office, news, prices, versions, results):

1. a **recent verified entry of the local reference** (checked less than
   180 days ago) answers at once and offline, with its date and source;
2. otherwise, with Settings › AI › "Search the web for current information"
   on (default), Wikipedia is looked up (only the question, shortened) and
   the sources are shown under the answer and kept in the store;
3. otherwise an older reference entry, with its date;
4. otherwise ZETA says it cannot verify, and the model is told not to name
   office holders or give results from its training data.

The reference is renewed with each release (`reference.json`, entries with
`verified` dates); `zeta --learn FILE` adds the user's own documents.

## Voice

Answers are **written and spoken together, by default** (new users and
users who never turned the voice off; an earlier "off" is kept). The voice
starts with the first sentence while the model is still writing: `speech.Stream`
cleans each finished sentence (`speech_text.normalize`: numbers, dates,
units, abbreviations as words; code blocks skipped) and writes it as a line
to the synthesizer, which turns lines into audio while `pw-play` plays the
previous one. The voice's model loads while the language model thinks.

| Language | Voice | Engine | License |
|---|---|---|---|
| Italian | Sara (`if_sara`), female | Kokoro-82M int8, ONNX Runtime, espeak-ng phonemes | Apache-2.0 |
| Italian (alternatives, low memory) | Serena, Paola, female | Piper | voices' own (see `/usr/share/zeta/legal/piper-voices`) |
| English | Lessac, female | Piper | voice's own |
| other languages | espeak-ng | espeak-ng | GPL-3.0-or-later |

The voice follows the language of the question (Italian or English), or the
system language when "Reply language" is set to it. One reading at a time:
a new answer stops the previous one; the microphone stops it before
listening. Under the input field: pause/resume, stop, read again. Escape
silences the voice first, then closes ZETA. Settings › AI › Voice: on/off,
voice per language, speed, volume. Kokoro falls back to Piper when less
than 900 MB are free. Synthesis runs at `nice 5`, like the model.

Measured in a 4-core virtual machine (Apple silicon host), October 2026:
Kokoro takes 1.5 s to the first audio when started cold (model load) and
synthesizes at about 0.7× real time alone, about 1× while the language model
writes; Piper starts in 0.5 s. Limiting Kokoro to two threads made no
measurable difference, so the default is kept. On an Intel N100 Kokoro may be
slower than real time while the model writes: the reading then has short
pauses between sentences; Serena (Piper) is the lighter choice there.

**Speech recognition** stays Vosk (offline, Italian and English, small
models, streaming). whisper.cpp was considered: it is not packaged in Debian
13 (only in forky/sid as of October 2026) and its smallest useful models cost
more processor time than Vosk on a 4-core machine while the language model
is loaded.

## Speed of the local model

On a processor every token of the prompt is read before the first word of
the answer, so ZETA sends the local model as little new text as possible.
The system prompt (persona and rules) is identical for every question; the
date, the web state, sources, reference, memories and reply language are a
short note added to the question and kept with it in the history, so Ollama
reuses everything it has already read (prefix cache). The history is
shortened in blocks, not one turn at a time, and its size follows the speed
measured on the computer (`~/.cache/zeta/ai-speed.json`). When the model is
loaded in advance (at login with 16 GB, or when ZETA opens) the fixed prompt
is read at the same time. Web sources for the local model are two excerpts
of 400 characters; reference entries are a few lines.

## Actions: closed catalog, verification, consent

The AI never runs arbitrary shell commands. A request goes through one chain:

1. **local understanding** (`agent/understanding.py`): English and Italian
   phrases are recognized in milliseconds, without the model; compound
   requests become several actions in order;
2. if that is not enough, **the model chooses one action** from the catalog
   (a JSON answer constrained to the action names; the arguments must appear
   in the request), only when the sentence talks about one;
3. actions that need consent **ask first**, showing what will be touched;
4. every action **checks the real state** of the system afterwards: the
   answer is the result of that check, never a courtesy "done".

The catalog (`agent/capabilities.py`) has 58 actions on apps, windows,
files and folders, settings, volume, brightness, Wi-Fi, Bluetooth, the Dock,
processes, software and the location of installed programs, with risk
levels read / normal / confirm. File operations are confined to the home
folder and external drives. Every action is written to
`~/.local/share/zeta/actions.log`, with passwords, keys and tokens hidden.

## Command line

```bash
zeta                      interactive conversation
zeta "how much disk space do I have?"
zeta --status             the local model, the profile, the installed models
zeta --memories           long-term memories
zeta --remember TEXT      add one
zeta --forget             clear the conversation
zeta --forget-all         clear the conversation and the long-term memories
zeta --learn FILE         index a text file as reference, locally
zeta ai status | ai test  details and a real test of the local model
```

`zeta-core` opens the graphical interface, with the particle sphere.

## Security and ethics

The system prompt tells the model to help willingly and to refuse only
requests that are clearly illegal or harm other people; security work on
the user's own or authorized systems is legitimate. ZETA has no action that
attacks other systems, never acts on its own initiative, and asks for
consent before anything destructive. The model runs as the `ollama` system
user, with `Nice=5`, `CPUWeight=30`, `MemoryHigh=45%`, `MemoryMax=60%`: it
can never take the desktop down with it.
