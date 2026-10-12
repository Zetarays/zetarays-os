# Contributing to ZETA RAYS OS

Thank you for helping. A few simple rules keep the system consistent.

1. **Open an issue first** for anything bigger than a typo, so we can agree on
   the idea before you spend time on it.
2. **One change per pull request**, with a short description of *why*.
3. **Test it**: build the image you touched (`./build.sh arm64` or `amd64`,
   see `docs/BUILD.md`), run `zeta-selftest` on it, and at least run the checks
   that run on every pull request (`.github/workflows/checks.yml`: shell
   syntax, Python, firewall syntax, translations, English-only source, no
   secrets).
4. **English in the source**: code, comments, docstrings, developer messages
   and documentation are written in English (`tools/check-italian.py`).
   Italian belongs only in the translations (`po/it.po`), in `*.it.md`
   documents and in data the system must recognize (Italian voice and text
   commands, marked `i18n-data`).
5. **User-facing text** is written in English inside `tr()`/`gettext` and
   translated in `po/it.po` (`python3 tools/i18n.py check` must pass). Follow
   the terminology in [`docs/GLOSSARY.md`](docs/GLOSSARY.md) (for example
   "click" in Italian too, "Support" for the project support link). No em
   dashes in texts shown to users.
6. **Keep the style**: comments explain *why*, not *what*. Do not rename
   public commands, files or configuration keys without a migration path.
7. **No secrets, no personal data** in commits: API keys, passwords, IP
   addresses of your machines.
8. **Licenses**: new code is GPL-3.0-or-later. Do not add fonts, images or
   other files whose license does not allow redistribution.
