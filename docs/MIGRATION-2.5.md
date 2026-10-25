# Moving from ZETA RAYS 2.1 to 2.5, and back

ZETA RAYS is installed from an image (ISO or OVA); there is no in-place
package upgrade of the ZETA RAYS components. Moving to 2.5 means installing
the 2.5 image. Debian packages keep updating as usual on both versions.

## Before you start

1. Back up your home folder (`/home/<you>`) to an external drive, for example
   with `rsync -aHAX --info=progress2 /home/<you>/ /media/<you>/<drive>/home-backup/`.
   Documents, pictures, settings and ZETA's memory all live there.
2. Write down the Wi-Fi passwords you need (Settings › Wi-Fi & Network).
3. Keep the 2.1 USB stick or image: it is the way back.

## Installing 2.5

- **Same disk, keeping /home**: in the installer choose *Manual
  partitioning*, select the existing `/home` partition (if you have one) and
  set it **not** to be formatted. If `/home` is not a separate partition, use
  the backup of step 1 instead.
- **New disk or virtual machine**: install normally, then copy your files
  back from the backup.

At the first login of a user who already used 2.1, `zeta-migrate-user`
brings the settings forward (a copy of every file it changes is kept in
`~/.local/state/zeta/migration-backup/`).

## What changes for your data

| 2.1 | 2.5 |
|---|---|
| Conversation in `~/.local/share/zeta/history.jsonl` | moved into `~/.local/share/zeta/memory.db` the first time ZETA starts; the old file is removed only after all its lines are in the new store |
| Online AI services and their API keys (`~/.config/zeta/keys/`) | not used any more: ZETA answers only with the local model. The encrypted key files are left where they are; delete the folder if you no longer need them |
| `"default"` provider and online service options in `~/.config/zeta/intelligence.json` | ignored |
| Voice off unless turned on | voice on by default; if you had turned it off (`~/.config/zeta/speech` contains `0`), it stays off |
| Local model `qwen3:4b-instruct` | still installed; ZETA picks the model that suits the computer (see docs/AI.md) |

## Going back to 2.1

1. Back up `~/.local/share/zeta/memory.db` if you want to keep what ZETA
   remembers (Settings › AI › Memory › Export writes a readable copy).
2. Install the 2.1 image (same procedure as above).
3. 2.1 does not read `memory.db`: it starts with an empty conversation.
   Your files and settings are unaffected.

## The 2.1 sources

The complete 2.1 build tree was archived and verified (checksum, file list,
sample restore) before any 2.5 change, next to the released 2.1 images,
which are unchanged.
